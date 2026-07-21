from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from linxira_completion_agent.backend import ComponentsBackend
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
            ]},
        ],
        "applications": [
            {"id": "chromium", "kind": "application", "primaryCategory": "apps", "name": {"en": "Chromium"}, "description": {"en": "Browser"}, "provider": "pacman", "source": "arch", "artifact": {"type": "package", "ids": ["chromium"]}, "license": {"spdx": "BSD-3-Clause", "requiresAcceptance": False}, "review": {"status": "reviewed"}, "availability": {"status": "available", "channel": "default"}, "sizeMiB": 300},
            {"id": "wps-office", "kind": "application", "primaryCategory": "apps", "name": {"en": "WPS"}, "description": {"en": "Office"}, "provider": "aur", "source": "aur", "artifact": {"type": "package", "ids": ["wps-office"]}, "license": {"spdx": "LicenseRef-WPS", "requiresAcceptance": True}, "review": {"status": "legal-review-pending"}, "availability": {"status": "review-channel", "channel": "optional-review", "reason": "Review pending"}, "sizeMiB": 900},
        ],
        "components": [
            {"id": "component-cups", "kind": "component", "name": {"en": "CUPS"}, "description": {"en": "Printing"}, "provider": "pacman", "source": "arch", "artifact": {"type": "package", "ids": ["cups"]}, "license": {"spdx": "Apache-2.0", "requiresAcceptance": False}, "review": {"status": "reviewed"}, "availability": {"status": "available", "channel": "default"}, "sizeMiB": 35},
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
            "selectedLeafIds": ["chromium", "wps-office"],
            "selectedBundleIds": ["apps"],
            "pendingItems": ["chromium", "wps-office"],
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_loads_metadata_and_classifies_provider_boundary(self) -> None:
        plan = load_completion_plan(self.catalog_path, self.receipt_path)
        self.assertEqual([item.id for item in plan.items], ["chromium", "wps-office"])
        self.assertTrue(plan.items[0].executable)
        self.assertFalse(plan.items[1].executable)
        self.assertTrue(plan.items[1].sensitive)

    def test_component_without_bundle_provenance_is_deferred(self) -> None:
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["selectedLeafIds"].append("component-cups")
        receipt["pendingItems"].append("component-cups")
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        plan = load_completion_plan(self.catalog_path, self.receipt_path)
        component = next(item for item in plan.items if item.id == "component-cups")
        self.assertFalse(component.executable)
        self.assertIn("bundle provenance", component.reason)

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

    def test_selection_contains_only_reviewed_arch_item(self) -> None:
        selection = build_selection(load_completion_plan(self.catalog_path, self.receipt_path))
        self.assertEqual(selection["selectedLeafIds"], ["chromium"])
        self.assertEqual(selection["providerRequirements"], ["pacman"])
        self.assertIn({"id": "wps-office", "selected": False}, selection["userOverrides"])

    def test_state_is_private_and_atomic(self) -> None:
        plan = load_completion_plan(self.catalog_path, self.receipt_path)
        target = self.root / "state/state.json"
        write_state(plan, "deferred", {"chromium": "deferred", "wps-office": "deferred"}, path=target)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["status"], "deferred")
        if os.name != "nt":
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_complete_state_is_bound_to_installer_receipt(self) -> None:
        plan = load_completion_plan(self.catalog_path, self.receipt_path)
        target = self.root / "state/state.json"
        write_state(plan, "complete", {"chromium": "succeeded", "wps-office": "deferred"}, path=target)
        self.assertTrue(is_complete(plan, path=target))
        document = json.loads(target.read_text(encoding="utf-8"))
        document["installerReceiptSha256"] = "0" * 64
        target.write_text(json.dumps(document), encoding="utf-8")
        self.assertFalse(is_complete(plan, path=target))

    @patch("linxira_completion_agent.backend.subprocess.run")
    def test_backend_uses_fixed_argv_without_shell(self, run) -> None:
        plan = load_completion_plan(self.catalog_path, self.receipt_path)

        def execute(command, **kwargs):
            output_dir = Path(command[command.index("--output-dir") + 1])
            (output_dir / "request-plan.json").write_text(json.dumps({"directPackageTargets": ["chromium"]}), encoding="utf-8")
            result = unittest.mock.Mock(returncode=0, stdout="{}", stderr="")
            return result

        run.side_effect = execute
        transaction = ComponentsBackend(self.catalog_path).create_plan(plan)
        command = run.call_args.args[0]
        self.assertEqual(command[0:2], ["linxira-components", "plan"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertNotIn("chromium", command)
        self.assertNotIn("wps-office", command)


if __name__ == "__main__":
    unittest.main()
