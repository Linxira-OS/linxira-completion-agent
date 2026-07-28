from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from linxira_completion_agent.model import CompletionError, load_completion_plan
from linxira_completion_agent.selection import build_selection
from linxira_completion_agent.state import is_complete, write_state


def catalog() -> dict:
    return {
        "catalogVersion": 3,
        "release": "test",
        "sources": [
            {"id": "arch", "name": {"en": "Arch"}, "trust": "distribution", "userOptInRequired": False},
            {"id": "aur", "name": {"en": "AUR"}, "trust": "user-opt-in", "userOptInRequired": True},
        ],
        "categories": [],
        "bundles": [
            {"id": "apps", "selection": {"mode": "multi"}, "children": [
            {"id": "chromium", "role": "optional"},
            {"id": "wps-office", "role": "optional"},
            {"id": "component-cups", "role": "optional"},
            ]},
        ],
        "applications": [
            {"id": "chromium", "kind": "application", "primaryCategory": "apps", "name": {"en": "Chromium"}, "description": {"en": "Browser"}, "provider": "pacman", "source": "arch", "artifact": {"type": "package", "ids": ["chromium"]}, "license": {"spdx": "BSD-3-Clause", "requiresAcceptance": False}, "review": {"status": "reviewed"}, "availability": {"status": "available", "channel": "default", "architectures": ["x86_64"]}, "sizeMiB": 300},
            {"id": "wps-office", "kind": "application", "primaryCategory": "apps", "name": {"en": "WPS"}, "description": {"en": "Office"}, "provider": "aur", "source": "aur", "artifact": {"type": "package", "ids": ["wps-office"]}, "license": {"spdx": "LicenseRef-WPS", "requiresAcceptance": True}, "review": {"status": "legal-review-pending"}, "availability": {"status": "review-channel", "channel": "optional-review", "reason": "Review pending"}, "sizeMiB": 900},
        ],
        "components": [
            {"id": "component-cups", "kind": "component", "name": {"en": "CUPS"}, "description": {"en": "Printing"}, "provider": "pacman", "source": "arch", "artifact": {"type": "package", "ids": ["cups"]}, "license": {"spdx": "Apache-2.0", "requiresAcceptance": False}, "review": {"status": "reviewed"}, "availability": {"status": "available", "channel": "default", "architectures": ["x86_64"]}, "sizeMiB": 35},
        ],
        "desktops": [
            {"id": "desktop-plasma", "kind": "desktop", "name": {"en": "Plasma"}, "description": {"en": "Desktop"}, "provider": "pacman", "source": "arch", "artifact": {"type": "package-group", "ids": ["plasma-meta"]}, "license": {"spdx": "GPL-2.0-or-later", "requiresAcceptance": False}, "review": {"status": "reviewed"}, "availability": {"status": "available", "channel": "default"}, "sizeMiB": 1000},
        ],
        "operations": [],
        "systemTools": [],
    }


class CompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.catalog_path = self.root / "catalog.json"
        self.receipt_path = self.root / "receipt.json"
        self.catalog_path.write_text(json.dumps(catalog()), encoding="utf-8")
        digest = hashlib.sha256(self.catalog_path.read_bytes()).hexdigest()
        self.receipt_path.write_text(json.dumps({
            "schemaVersion": "org.linxira.installer.selection-receipt.v1",
            "catalogSha256": digest,
            "catalogRelease": "test",
            "selectedLeafIds": ["chromium", "wps-office"],
            "selectedBundleIds": ["apps"],
            "satisfiedItems": ["chromium"],
            "pendingItems": ["wps-office"],
            "installedItems": ["chromium"],
            "deferredItems": ["wps-office"],
            "itemStatuses": [
                {"id": "chromium", "status": "installed"},
                {"id": "wps-office", "status": "explicitly-deferred"},
            ],
            "status": "installed",
            "selectionDocument": {
                "schemaVersion": "org.linxira.component-selection.v1",
                "catalogSha256": digest,
                "catalogRelease": "test",
                "selectedLeafIds": ["chromium", "wps-office"],
                "selectedBundleIds": ["apps"],
            },
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_loads_metadata_and_classifies_provider_boundary(self) -> None:
        plan = load_completion_plan(self.catalog_path, self.receipt_path)
        self.assertEqual([item.id for item in plan.items], ["wps-office"])
        self.assertFalse(plan.items[0].executable)
        self.assertTrue(plan.items[0].sensitive)

    def test_official_only_receipt_has_no_first_boot_items(self) -> None:
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["selectedLeafIds"] = ["chromium"]
        receipt["satisfiedItems"] = ["chromium"]
        receipt["pendingItems"] = []
        receipt["installedItems"] = ["chromium"]
        receipt["deferredItems"] = []
        receipt["itemStatuses"] = [{"id": "chromium", "status": "installed"}]
        receipt["selectionDocument"]["selectedLeafIds"] = ["chromium"]
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

        self.assertEqual(load_completion_plan(self.catalog_path, self.receipt_path).items, ())

    def test_reviewed_arch_component_cannot_be_deferred_to_completion(self) -> None:
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["selectedLeafIds"].append("component-cups")
        receipt["pendingItems"].append("component-cups")
        receipt["deferredItems"].append("component-cups")
        receipt["itemStatuses"].append(
            {"id": "component-cups", "status": "explicitly-deferred"}
        )
        receipt["selectionDocument"]["selectedLeafIds"].append("component-cups")
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(CompletionError, "before first boot: component-cups"):
            load_completion_plan(self.catalog_path, self.receipt_path)

    def test_operation_dependent_arch_component_may_be_explicitly_deferred(self) -> None:
        document = catalog()
        document["components"][0]["requires"] = ["operation-enable-cups"]
        document["components"].append({
            "id": "component-printer-config",
            "kind": "component",
            "name": {"en": "Printer configuration"},
            "description": {"en": "Configure printers"},
            "provider": "pacman",
            "source": "arch",
            "artifact": {"type": "package", "ids": ["system-config-printer"]},
            "license": {"spdx": "GPL-2.0-or-later", "requiresAcceptance": False},
            "review": {"status": "reviewed"},
            "availability": {"status": "available", "channel": "default", "architectures": ["x86_64"]},
            "requires": ["component-cups"],
        })
        document["operations"] = [{
            "id": "operation-enable-cups",
            "kind": "operation",
            "name": {"en": "Enable CUPS"},
            "description": {"en": "Enable the reviewed service"},
            "provider": "builtin",
            "source": "linxira-operations",
            "availability": {"status": "available"},
        }]
        self.catalog_path.write_text(json.dumps(document), encoding="utf-8")
        digest = hashlib.sha256(self.catalog_path.read_bytes()).hexdigest()
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["catalogSha256"] = digest
        receipt["selectionDocument"]["catalogSha256"] = digest
        receipt["selectedLeafIds"].append("component-cups")
        receipt["pendingItems"].append("component-cups")
        receipt["deferredItems"].append("component-cups")
        receipt["itemStatuses"].append(
            {"id": "component-cups", "status": "explicitly-deferred"}
        )
        receipt["selectionDocument"]["selectedLeafIds"].append("component-cups")
        receipt["selectedLeafIds"].append("component-printer-config")
        receipt["pendingItems"].append("component-printer-config")
        receipt["deferredItems"].append("component-printer-config")
        receipt["itemStatuses"].append(
            {"id": "component-printer-config", "status": "explicitly-deferred"}
        )
        receipt["selectionDocument"]["selectedLeafIds"].append("component-printer-config")
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

        plan = load_completion_plan(self.catalog_path, self.receipt_path)
        cups = next(item for item in plan.items if item.id == "component-cups")
        self.assertFalse(cups.executable)
        self.assertIn("system operation", cups.reason)
        printer = next(item for item in plan.items if item.id == "component-printer-config")
        self.assertFalse(printer.executable)
        self.assertIn("system operation", printer.reason)

    def test_desktop_is_recognized_but_never_executable(self) -> None:
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["selectedLeafIds"].append("desktop-plasma")
        receipt["pendingItems"].append("desktop-plasma")
        receipt["deferredItems"].append("desktop-plasma")
        receipt["itemStatuses"].append(
            {"id": "desktop-plasma", "status": "explicitly-deferred"}
        )
        receipt["selectionDocument"]["selectedLeafIds"].append("desktop-plasma")
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(CompletionError, "before first boot: desktop-plasma"):
            load_completion_plan(self.catalog_path, self.receipt_path)

    def test_desktop_cannot_claim_application_kind(self) -> None:
        document = catalog()
        document["desktops"][0]["kind"] = "application"
        self.catalog_path.write_text(json.dumps(document), encoding="utf-8")
        digest = hashlib.sha256(self.catalog_path.read_bytes()).hexdigest()
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["catalogSha256"] = digest
        receipt["selectionDocument"]["catalogSha256"] = digest
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(CompletionError, "invalid desktops leaf kind"):
            load_completion_plan(self.catalog_path, self.receipt_path)

    def test_inconsistent_nested_selection_is_rejected(self) -> None:
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["selectionDocument"]["selectedLeafIds"] = ["chromium"]
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(CompletionError, "inconsistent"):
            load_completion_plan(self.catalog_path, self.receipt_path)

    def test_rejects_catalog_drift(self) -> None:
        self.catalog_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(CompletionError, "Catalog v3|catalog changed"):
            load_completion_plan(self.catalog_path, self.receipt_path)

    def test_rejects_unknown_and_duplicate_pending_ids(self) -> None:
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["pendingItems"] = ["missing", "missing"]
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(CompletionError, "duplicate"):
            load_completion_plan(self.catalog_path, self.receipt_path)

    def test_deferred_plan_has_no_executable_official_selection(self) -> None:
        with self.assertRaisesRegex(CompletionError, "no reviewed Arch items"):
            build_selection(load_completion_plan(self.catalog_path, self.receipt_path))

    def test_receipt_status_disagreement_is_rejected(self) -> None:
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["installedItems"] = []
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(CompletionError, "classifications disagree"):
            load_completion_plan(self.catalog_path, self.receipt_path)

    def test_state_is_private_and_atomic(self) -> None:
        plan = load_completion_plan(self.catalog_path, self.receipt_path)
        target = self.root / "state/state.json"
        write_state(plan, "deferred", {"wps-office": "deferred"}, path=target)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["status"], "deferred")
        if os.name != "nt":
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_complete_state_is_bound_to_installer_receipt(self) -> None:
        plan = load_completion_plan(self.catalog_path, self.receipt_path)
        target = self.root / "state/state.json"
        write_state(plan, "complete", {"wps-office": "deferred"}, path=target)
        self.assertTrue(is_complete(plan, path=target))
        document = json.loads(target.read_text(encoding="utf-8"))
        document["installerReceiptSha256"] = "0" * 64
        target.write_text(json.dumps(document), encoding="utf-8")
        self.assertFalse(is_complete(plan, path=target))

if __name__ == "__main__":
    unittest.main()
