# -*- coding: utf-8 -*-
"""Geometry group analysis Skill."""

SKILL_INFO = {
    "name": "analyze_groups",
    "category": "geometry",
    "description": (
        "Analyze SOP geometry point, primitive, and edge groups. Reports group "
        "sizes, empty groups, and compact membership samples. Read-only."
    ),
    "risk_level": "low",
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "SOP node path, for example /obj/geo1/OUT.",
            "required": True,
        },
        "include_members": {
            "type": "boolean",
            "description": "Include limited member number samples for each group.",
            "required": False,
            "default": False,
        },
        "max_members": {
            "type": "integer",
            "description": "Maximum sampled member numbers per group when include_members is true.",
            "required": False,
            "default": 20,
        },
    },
}


def _safe_len(value):
    try:
        return len(value)
    except Exception:
        return 0


def _group_members(group, method_name):
    method = getattr(group, method_name, None)
    if not callable(method):
        return []
    try:
        return list(method())
    except Exception:
        return []


def _item_number(item):
    try:
        return item.number()
    except Exception:
        return str(item)


def _summarize_group(group, member_method, include_members, max_members):
    members = _group_members(group, member_method)
    summary = {
        "name": group.name(),
        "size": _safe_len(members),
        "is_empty": _safe_len(members) == 0,
    }
    if include_members:
        sample = members[:max_members]
        summary["member_sample"] = [_item_number(item) for item in sample]
        summary["members_truncated"] = len(members) > len(sample)
    return summary


def _summarize_group_class(geo, class_name, list_method_name, member_method, include_members, max_members):
    list_method = getattr(geo, list_method_name, None)
    groups = []
    if callable(list_method):
        try:
            groups = list(list_method())
        except Exception:
            groups = []

    summaries = [
        _summarize_group(group, member_method, include_members, max_members)
        for group in groups
    ]
    return {
        "class": class_name,
        "count": len(summaries),
        "empty_count": sum(1 for group in summaries if group["is_empty"]),
        "groups": summaries,
    }


def run(node_path, include_members=False, max_members=20):
    """Analyze geometry groups on a SOP node."""
    import hou  # type: ignore

    node = hou.node(node_path)
    if not node:
        return {"error": f"Node does not exist: {node_path}"}

    try:
        geo = node.geometry()
    except Exception as exc:
        return {"error": f"Could not read geometry from {node_path}: {exc}"}
    if geo is None:
        return {"error": f"Node has no readable geometry: {node_path}"}

    max_members = max(0, min(int(max_members), 200))
    group_classes = [
        _summarize_group_class(geo, "point", "pointGroups", "points", include_members, max_members),
        _summarize_group_class(geo, "primitive", "primGroups", "prims", include_members, max_members),
        _summarize_group_class(geo, "edge", "edgeGroups", "edges", include_members, max_members),
    ]

    return {
        "node_path": node_path,
        "group_class_count": len(group_classes),
        "total_groups": sum(group_class["count"] for group_class in group_classes),
        "total_empty_groups": sum(group_class["empty_count"] for group_class in group_classes),
        "groups_by_class": group_classes,
    }