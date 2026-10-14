# -*- coding: utf-8 -*-
"""Compare two bounded Houdini network snapshots."""

from typing import Any, Dict, List




def _flatten(snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result = {}

    def visit(node: Dict[str, Any]) -> None:
        path = node.get("path")
        if path:
            result[path] = node
        for child in node.get("children", []) or []:
            visit(child)

    scene = snapshot.get("scene", snapshot)
    if isinstance(scene, dict):
        visit(scene)
    return result


def compare_snapshots(before_snapshot: Dict[str, Any], after_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    before = _flatten(before_snapshot)
    after = _flatten(after_snapshot)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = []
    health_changes = []
    for path in sorted(set(before) & set(after)):
        old = before[path]
        new = after[path]
        changes = {}
        for key in ("type", "input_count", "output_count", "flags", "parameters"):
            if old.get(key) != new.get(key):
                changes[key] = {"before": old.get(key), "after": new.get(key)}
        if changes:
            changed.append({"path": path, "changes": changes})
        for key in ("has_errors", "has_warnings"):
            if old.get(key) != new.get(key):
                health_changes.append({"path": path, "field": key, "before": old.get(key), "after": new.get(key)})
    resolved = [item for item in health_changes if item["before"] is True and item["after"] is False]
    introduced = [item for item in health_changes if item["before"] is False and item["after"] is True]
    draft = (
        "Houdini 网络修改经验\n"
        f"新增节点: {', '.join(added) or '无'}\n"
        f"删除节点: {', '.join(removed) or '无'}\n"
        f"变化节点数: {len(changed)}\n"
        f"解决的健康问题: {len(resolved)}；新增健康问题: {len(introduced)}\n"
        "复用前应结合目标任务确认这些变化是否为因果改进，而非仅时间相关。"
    )[:2000]
    return {
        "added_nodes": added,
        "removed_nodes": removed,
        "changed_nodes": changed,
        "health_changes": health_changes,
        "resolved_issues": resolved,
        "introduced_issues": introduced,
        "memory_draft": draft,
    }


def run(before_snapshot: Dict[str, Any], after_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return compare_snapshots(before_snapshot, after_snapshot)