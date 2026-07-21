from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


class CompletionError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CompletionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _document(raw: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompletionError(f"invalid {description}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompletionError(f"{description} must be a JSON object")
    return value


def _ids(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise CompletionError(f"{field} must be a string array")
    if len(value) != len(set(value)):
        raise CompletionError(f"{field} contains duplicate IDs")
    return value


@dataclass(frozen=True)
class CompletionItem:
    id: str
    kind: str
    name: str
    description: str
    provider: str
    source: str
    source_name: str
    source_trust: str
    size_mib: int
    license_id: str
    requires_acceptance: bool
    repository_change: str
    executable: bool
    sensitive: bool
    reason: str


@dataclass(frozen=True)
class CompletionPlan:
    catalog: dict[str, Any]
    receipt: dict[str, Any]
    catalog_sha256: str
    receipt_sha256: str
    items: tuple[CompletionItem, ...]


def _localized(value: Any, locale: str) -> str:
    if not isinstance(value, dict):
        return ""
    selected = value.get(locale) or value.get("en")
    return selected if isinstance(selected, str) else ""


def load_completion_plan(catalog_path: Path, receipt_path: Path, *, locale: str = "en") -> CompletionPlan:
    if catalog_path.is_symlink() or receipt_path.is_symlink():
        raise CompletionError("catalog and installer receipt must not be symlinks")
    try:
        catalog_raw = catalog_path.read_bytes()
        receipt_raw = receipt_path.read_bytes()
    except OSError as exc:
        raise CompletionError(str(exc)) from exc
    catalog = _document(catalog_raw, "Catalog v3")
    receipt = _document(receipt_raw, "installer selection receipt")
    catalog_digest = hashlib.sha256(catalog_raw).hexdigest()
    receipt_digest = hashlib.sha256(receipt_raw).hexdigest()

    if catalog.get("catalogVersion") != 3:
        raise CompletionError("Completion Agent requires Catalog v3")
    if receipt.get("schemaVersion") != "org.linxira.installer.selection-receipt.v1":
        raise CompletionError("unsupported installer selection receipt")
    if receipt.get("catalogSha256") != catalog_digest:
        raise CompletionError("catalog changed after the installer selection was recorded")
    selected = _ids(receipt.get("selectedLeafIds"), "selectedLeafIds")
    _ids(receipt.get("selectedBundleIds"), "selectedBundleIds")
    pending = _ids(receipt.get("pendingItems"), "pendingItems")
    if not set(pending).issubset(selected):
        raise CompletionError("pendingItems must be a subset of selectedLeafIds")

    sources = {
        item["id"]: item for item in catalog.get("sources", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    leaves: dict[str, dict[str, Any]] = {}
    for collection in ("applications", "components", "operations", "systemTools"):
        for item in catalog.get(collection, []):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                if item["id"] in leaves:
                    raise CompletionError(f"duplicate catalog leaf ID: {item['id']}")
                leaves[item["id"]] = item

    items: list[CompletionItem] = []
    for leaf_id in pending:
        leaf = leaves.get(leaf_id)
        if leaf is None:
            raise CompletionError(f"pending item is not a Catalog v3 leaf: {leaf_id}")
        source_id = leaf.get("source")
        kind = leaf.get("kind") if isinstance(leaf.get("kind"), str) else "unknown"
        source = sources.get(source_id, {})
        provider = leaf.get("provider") if isinstance(leaf.get("provider"), str) else "unknown"
        license_info = leaf.get("license") if isinstance(leaf.get("license"), dict) else {}
        availability = leaf.get("availability") if isinstance(leaf.get("availability"), dict) else {}
        review = leaf.get("review") if isinstance(leaf.get("review"), dict) else {}
        requires_acceptance = license_info.get("requiresAcceptance") is True
        user_opt_in = source.get("userOptInRequired") is True
        executable = (
            kind == "application" and provider == "pacman" and source_id == "arch"
            and availability.get("status") == "available"
            and availability.get("channel") == "default"
            and review.get("status") == "reviewed"
        )
        repository_change = "None"
        if leaf_id == "steam":
            repository_change = "Enable Arch multilib"
        elif user_opt_in:
            repository_change = f"Enable {source_id} (provider not implemented)"
        if executable:
            reason = "Ready through official Arch repositories"
        elif kind != "application" and provider == "pacman" and source_id == "arch":
            reason = "Deferred until the installer receipt stores complete component bundle provenance"
        else:
            reason = (
                availability.get("reason") if isinstance(availability.get("reason"), str)
                else "The required provider or review contract is not implemented"
            )
        items.append(CompletionItem(
            id=leaf_id,
            kind=kind,
            name=_localized(leaf.get("name"), locale) or leaf_id,
            description=_localized(leaf.get("description"), locale),
            provider=provider,
            source=str(source_id or "unknown"),
            source_name=_localized(source.get("name"), locale) or str(source_id or "unknown"),
            source_trust=str(source.get("trust", "unknown")),
            size_mib=leaf.get("sizeMiB") if isinstance(leaf.get("sizeMiB"), int) else 0,
            license_id=str(license_info.get("spdx", "unknown")),
            requires_acceptance=requires_acceptance,
            repository_change=repository_change,
            executable=executable,
            sensitive=requires_acceptance or user_opt_in or provider != "pacman" or leaf_id == "steam",
            reason=reason,
        ))
    return CompletionPlan(catalog, receipt, catalog_digest, receipt_digest, tuple(items))
