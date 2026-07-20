from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from .model import CompletionError, CompletionPlan
from .selection import build_selection


@dataclass(frozen=True)
class Transaction:
    directory: Path
    plan: dict[str, Any]


class ComponentsBackend:
    def __init__(self, catalog_path: Path, *, executable: str = "linxira-components", pkexec: str = "pkexec") -> None:
        self.catalog_path = catalog_path
        self.executable = executable
        self.pkexec = pkexec

    @staticmethod
    def _run(command: list[str], timeout: int = 30) -> str:
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout, shell=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CompletionError(f"cannot run {command[0]}: {exc}") from exc
        if result.returncode:
            raise CompletionError((result.stderr or result.stdout or f"exit code {result.returncode}").strip())
        return result.stdout.strip()

    def create_plan(self, completion: CompletionPlan) -> Transaction:
        selection = build_selection(completion)
        directory = Path(tempfile.mkdtemp(prefix="linxira-completion-"))
        try:
            selection_path = directory / "selection.json"
            selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self._run([self.executable, "plan", "--catalog", str(self.catalog_path), "--selection", str(selection_path), "--output-dir", str(directory)])
            plan_path = directory / "request-plan.json"
            document = json.loads(plan_path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or not isinstance(document.get("directPackageTargets"), list):
                raise CompletionError("transaction backend produced an invalid request plan")
            return Transaction(directory, document)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def confirm_and_apply(self, transaction: Transaction) -> dict[str, Any]:
        try:
            self._run([self.executable, "confirm", "--catalog", str(self.catalog_path), "--plan", str(transaction.directory / "request-plan.json"), "--output-dir", str(transaction.directory)])
            output = self._run([self.pkexec, self.executable, "apply", "--catalog", str(self.catalog_path), "--confirmation", str(transaction.directory / "confirmation.json")], timeout=3600)
            value = json.loads(output)
            if not isinstance(value, dict) or value.get("status") != "succeeded":
                raise CompletionError("transaction backend did not return a successful receipt")
            return value
        finally:
            shutil.rmtree(transaction.directory, ignore_errors=True)
