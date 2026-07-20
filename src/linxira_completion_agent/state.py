from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .model import CompletionPlan


def state_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return base / "linxira/completion/state.json"


def read_state(plan: CompletionPlan, *, path: Path | None = None) -> dict[str, Any] | None:
    target = state_path() if path is None else path
    if target.is_symlink():
        return None
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not (
        isinstance(document, dict)
        and document.get("schemaVersion") == "org.linxira.completion-state.v1"
        and document.get("installerReceiptSha256") == plan.receipt_sha256
        and document.get("catalogSha256") == plan.catalog_sha256
    ):
        return None
    return document


def is_complete(plan: CompletionPlan, *, path: Path | None = None) -> bool:
    document = read_state(plan, path=path)
    return document is not None and document.get("status") == "complete"


def write_state(plan: CompletionPlan, status: str, item_statuses: dict[str, str], *, message: str = "", path: Path | None = None) -> Path:
    target = state_path() if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    document: dict[str, Any] = {
        "schemaVersion": "org.linxira.completion-state.v1",
        "installerReceiptSha256": plan.receipt_sha256,
        "catalogSha256": plan.catalog_sha256,
        "status": status,
        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": message,
        "items": [{"id": item.id, "status": item_statuses.get(item.id, "pending")} for item in plan.items],
    }
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
