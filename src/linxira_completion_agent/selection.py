from __future__ import annotations

from typing import Any

from .model import CompletionError, CompletionPlan


def _children(bundle: dict[str, Any]) -> list[tuple[str, str]]:
    value = bundle.get("children", [])
    if isinstance(value, list):
        return [
            (item, "optional") if isinstance(item, str) else (item["id"], item["role"])
            for item in value
            if isinstance(item, str) or (
                isinstance(item, dict) and isinstance(item.get("id"), str)
                and item.get("role") in {"required", "recommended", "optional"}
            )
        ]
    if isinstance(value, dict):
        return [
            (item, role)
            for role in ("required", "recommended", "optional")
            for item in value.get(role, [])
            if isinstance(item, str)
        ]
    return []


def build_selection(plan: CompletionPlan) -> dict[str, Any]:
    selected = {item.id for item in plan.items if item.executable}
    if not selected:
        raise CompletionError("no reviewed Arch items are ready to complete")
    leaves = {
        item["id"]: item
        for collection in ("applications", "components", "desktops", "operations", "systemTools")
        for item in plan.catalog.get(collection, [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    bundles = {
        item["id"]: item
        for collection in ("bundles",)
        for item in plan.catalog.get(collection, [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    def find_path(node_id: str, target: str, active: frozenset[str] = frozenset()) -> list[str] | None:
        if node_id in active:
            raise CompletionError("catalog bundle graph contains a cycle")
        for child_id, _ in _children(bundles[node_id]):
            if child_id == target:
                return [node_id, target]
            if child_id in bundles:
                nested = find_path(child_id, target, active | {node_id})
                if nested:
                    return [node_id, *nested]
        return None

    paths: dict[str, list[str]] = {}
    roots: set[str] = set()
    for leaf_id in sorted(selected):
        primary = leaves[leaf_id].get("primaryCategory")
        candidates = [primary] if isinstance(primary, str) and primary in bundles else sorted(bundles)
        path = next((result for root in candidates if (result := find_path(root, leaf_id))), None)
        if path is None:
            raise CompletionError(f"catalog leaf has no selectable path: {leaf_id}")
        paths[leaf_id] = path
        roots.add(path[0])

    active_bundles: set[str] = set()
    descendant_leaves: set[str] = set()

    def walk(node_id: str) -> None:
        if node_id in active_bundles:
            return
        active_bundles.add(node_id)
        for child_id, _ in _children(bundles[node_id]):
            if child_id in bundles:
                walk(child_id)
            elif child_id in leaves:
                descendant_leaves.add(child_id)

    for root in roots:
        walk(root)

    constraints = []
    for bundle_id, bundle in sorted(bundles.items()):
        chosen = 0
        for child_id, _ in _children(bundle):
            child_leaves: set[str] = set()
            if child_id in leaves:
                child_leaves.add(child_id)
            elif child_id in bundles:
                stack = [child_id]
                while stack:
                    current = stack.pop()
                    for nested_id, _ in _children(bundles[current]):
                        if nested_id in leaves:
                            child_leaves.add(nested_id)
                        elif nested_id in bundles:
                            stack.append(nested_id)
            chosen += bool(selected & child_leaves)
        selection = bundle.get("selection", {})
        mode = selection.get("mode") if isinstance(selection, dict) else selection
        maximum = 1 if mode == "exclusive" else selection.get("maxSelected") if isinstance(selection, dict) and mode == "bounded" else None
        constraints.append({"bundleId": bundle_id, "policy": mode, "selectedCount": chosen, "maxSelected": maximum, "valid": maximum is None or chosen <= maximum})

    return {
        "schemaVersion": "org.linxira.component-selection.v1",
        "catalogSha256": plan.catalog_sha256,
        "catalogRelease": str(plan.catalog.get("release", "")),
        "selectedLeafIds": sorted(selected),
        "selectedBundleIds": sorted(active_bundles),
        "leaves": [
            {"id": leaf_id, "requestedBy": ["/".join(paths[leaf_id])], "provenance": ["optional", "user"]}
            for leaf_id in sorted(selected)
        ],
        "userOverrides": [
            {"id": leaf_id, "selected": leaf_id in selected}
            for leaf_id in sorted(descendant_leaves)
        ],
        "constraintResults": constraints,
        "providerRequirements": sorted({str(leaves[item]["provider"]) for item in selected}),
        "sourceRequirements": sorted({str(leaves[item]["source"]) for item in selected}),
    }
