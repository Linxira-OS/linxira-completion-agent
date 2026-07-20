from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .backend import ComponentsBackend
from .model import CompletionError, CompletionPlan, load_completion_plan
from .state import read_state, write_state


CATALOG_PATH = Path("/usr/share/linxira/catalog/catalog-v3.json")
RECEIPT_PATH = Path("/var/lib/linxira/installer-selection.json")


def online() -> bool:
    try:
        result = subprocess.run(["nmcli", "--terse", "networking", "connectivity", "check"], check=False, capture_output=True, text=True, timeout=5, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() in {"full", "limited", "portal"}


class ApplyThread(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, completion: CompletionPlan, backend: ComponentsBackend) -> None:
        super().__init__()
        self.completion = completion
        self.backend = backend

    def run(self) -> None:
        try:
            transaction = self.backend.create_plan(self.completion)
            self.succeeded.emit(self.backend.confirm_and_apply(transaction))
        except Exception as exc:
            self.failed.emit(str(exc))


class CompletionWindow(QWidget):
    def __init__(self, completion: CompletionPlan, catalog_path: Path) -> None:
        super().__init__()
        self.completion = completion
        self.backend = ComponentsBackend(catalog_path)
        self.acceptances: list[QCheckBox] = []
        self.thread: ApplyThread | None = None
        self.setWindowTitle("Linxira Completion")
        self.resize(880, 560)

        layout = QVBoxLayout(self)
        title = QLabel("Complete your installation")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)
        self.network_label = QLabel()
        layout.addWidget(self.network_label)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Software", "Source", "Size", "License", "Repository change", "State"])
        tree.setRootIsDecorated(False)
        for item in completion.items:
            row = QTreeWidgetItem([
                item.name, f"{item.source_name} ({item.source_trust})", f"{item.size_mib} MiB",
                item.license_id, item.repository_change, "Ready" if item.executable else "Deferred",
            ])
            row.setToolTip(0, f"{item.description}\n{item.reason}")
            tree.addTopLevelItem(row)
            if item.sensitive:
                checkbox = QCheckBox(f"I confirm the source and license conditions for {item.name}")
                checkbox.stateChanged.connect(self.refresh)
                self.acceptances.append(checkbox)
                layout.addWidget(checkbox)
        tree.resizeColumnToContents(0)
        layout.addWidget(tree, 1)

        buttons = QHBoxLayout()
        self.defer_button = QPushButton("Defer")
        self.defer_button.clicked.connect(self.defer)
        self.apply_button = QPushButton("Complete ready items")
        self.apply_button.clicked.connect(self.apply)
        buttons.addStretch(1)
        buttons.addWidget(self.defer_button)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(15000)
        self.refresh()

    def refresh(self) -> None:
        connected = online()
        ready = any(item.executable for item in self.completion.items)
        accepted = all(box.isChecked() for box in self.acceptances)
        self.network_label.setText("Network is available." if connected else "Waiting for a network connection.")
        self.apply_button.setEnabled(connected and ready and accepted and self.thread is None)

    def defer(self) -> None:
        write_state(self.completion, "deferred", {item.id: "deferred" for item in self.completion.items}, message="Completion was deferred by the user")
        self.close()

    def apply(self) -> None:
        self.apply_button.setEnabled(False)
        self.defer_button.setEnabled(False)
        write_state(self.completion, "applying", {}, message="Applying reviewed Arch items")
        self.thread = ApplyThread(self.completion, self.backend)
        self.thread.succeeded.connect(self.completed)
        self.thread.failed.connect(self.failed)
        self.thread.start()

    def completed(self, receipt: dict) -> None:
        statuses = {item.id: "succeeded" if item.executable else "deferred" for item in self.completion.items}
        final = "complete" if all(value == "succeeded" for value in statuses.values()) else "deferred"
        write_state(self.completion, final, statuses, message=f"Backend receipt {receipt.get('id', 'unknown')}")
        QMessageBox.information(self, "Linxira Completion", "Ready items were installed. Deferred providers were not executed.")
        self.close()

    def failed(self, message: str) -> None:
        self.thread = None
        write_state(self.completion, "failed", {}, message=message)
        self.defer_button.setEnabled(True)
        self.refresh()
        QMessageBox.critical(self, "Completion failed", message)


def main() -> int:
    parser = argparse.ArgumentParser(prog="linxira-completion-agent")
    parser.add_argument("--autostart", action="store_true")
    args = parser.parse_args()
    try:
        completion = load_completion_plan(CATALOG_PATH, RECEIPT_PATH)
    except CompletionError as exc:
        print(f"linxira-completion-agent: {exc}", file=sys.stderr)
        return 2
    previous = read_state(completion)
    if args.autostart and previous is not None and previous.get("status") in {"complete", "deferred"}:
        return 0
    succeeded = {
        item.get("id") for item in previous.get("items", [])
        if isinstance(item, dict) and item.get("status") == "succeeded"
    } if previous is not None else set()
    completion = replace(completion, items=tuple(item for item in completion.items if item.id not in succeeded))
    if not completion.items:
        return 0
    app = QApplication(sys.argv)
    window = CompletionWindow(completion, CATALOG_PATH)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
