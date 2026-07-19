# -*- coding: utf-8 -*-
"""Network contract validation Skill."""

SKILL_INFO = {
    "name": "validate_network_contract",
    "category": "graph",
    "description": (
        "Validate a Houdini network for common pipeline contract issues: OUT/null naming, "
        "display/render flags, missing inputs, bypass/locked nodes, errors/warnings, and dead nodes. Read-only."
    ),
    "risk_level": "low",
    "parameters": {
        "network_path": {
            "type": "string",
            "description": "Network path to validate, for example /obj/geo1.",
            "required": True,
        },
        "recursive": {
            "type": "boolean",
            "description": "Whether to include child subnet contents. Defaults to false.",
            "required": False,
            "default": False,
        },
        "max_nodes": {
            "type": "integer",
            "description": "Maximum nodes to inspect before truncating. Defaults to 1000.",
            "required": False,
            "default": 1000,
        },
    },
}


def _safe_call(func, default=None):
    try:
        return func()
    except Exception:
        return default


def _node_info(node):
    return {
        "name": node.name(),
        "path": node.path(),
        "type": _safe_call(lambda: node.type().name(), ""),
    }


def _flag(node, method_name):
    method = getattr(node, method_name, None)
    if not callable(method):
        return False
    return bool(_safe_call(method, False))


def _messages(node, method_name):
    method = getattr(node, method_name, None)
    if not callable(method):
        return []
    values = _safe_call(method, []) or []
    return [str(value) for value in values]


def _required_input_count(node):
    node_type = _safe_call(lambda: node.type(), None)
    if node_type is None:
        return 0
    min_inputs = getattr(node_type, "minNumInputs", None)
    if callable(min_inputs):
        try:
            return max(0, int(min_inputs()))
        except Exception:
            return 0
    return 0


def _collect_nodes(network, recursive, max_nodes):
    if recursive:
        nodes = list(_safe_call(lambda: network.allSubChildren(), ()) or ())
    else:
        nodes = list(_safe_call(lambda: network.children(), ()) or ())
    truncated = len(nodes) > max_nodes
    return nodes[:max_nodes], truncated


def _issue(severity, code, node, message, suggestion):
    data = {
        "severity": severity,
        "code": code,
        "message": message,
        "suggestion": suggestion,
    }
    if node is not None:
        data["node"] = _node_info(node)
    return data


def run(network_path, recursive=False, max_nodes=1000):
    """Validate common Houdini network contract issues without mutating the scene."""
    import hou  # type: ignore

    network = hou.node(network_path)
    if not network:
        return {"error": f"Network does not exist: {network_path}"}

    max_nodes = max(1, min(int(max_nodes), 10000))
    nodes, truncated = _collect_nodes(network, bool(recursive), max_nodes)
    issues = []
    display_nodes = []
    render_nodes = []
    terminal_nodes = []
    out_like_nodes = []
    dead_nodes = []
    bypassed_nodes = []
    locked_nodes = []
    error_nodes = []
    warning_nodes = []
    missing_input_nodes = []

    for node in nodes:
        info = _node_info(node)
        name_upper = info["name"].upper()
        type_name = str(info["type"] or "").lower()
        inputs = list(_safe_call(lambda n=node: n.inputs(), ()) or ())
        outputs = list(_safe_call(lambda n=node: n.outputs(), ()) or ())
        connected_inputs = [item for item in inputs if item is not None]

        if _flag(node, "isDisplayFlagSet"):
            display_nodes.append(info)
        if _flag(node, "isRenderFlagSet"):
            render_nodes.append(info)
        if not outputs:
            terminal_nodes.append(info)
        if name_upper.startswith("OUT") or type_name == "null":
            out_like_nodes.append(info)

        if not outputs and not _flag(node, "isDisplayFlagSet") and not _flag(node, "isRenderFlagSet"):
            dead_nodes.append(info)
            issues.append(_issue(
                "warning",
                "dead_node",
                node,
                "Node has no downstream outputs and is not display/render flagged.",
                "Remove it, connect it downstream, or mark the intended output/display node.",
            ))

        if _flag(node, "isBypassed"):
            bypassed_nodes.append(info)
            issues.append(_issue("info", "bypassed_node", node, "Node is bypassed.", "Confirm the bypass is intentional."))
        if _flag(node, "isLocked"):
            locked_nodes.append(info)
            issues.append(_issue("info", "locked_node", node, "Node is locked.", "Unlock only if edits are expected."))

        errors = _messages(node, "errors")
        warnings = _messages(node, "warnings")
        if errors:
            error_nodes.append({**info, "errors": errors})
            issues.append(_issue("error", "node_errors", node, "; ".join(errors[:3]), "Open the node and fix reported errors."))
        if warnings:
            warning_nodes.append({**info, "warnings": warnings})
            issues.append(_issue("warning", "node_warnings", node, "; ".join(warnings[:3]), "Review the warning and decide if it is acceptable."))

        required_inputs = _required_input_count(node)
        if required_inputs and len(connected_inputs) < required_inputs:
            missing_input_nodes.append({**info, "required_inputs": required_inputs, "connected_inputs": len(connected_inputs)})
            issues.append(_issue(
                "warning",
                "missing_required_inputs",
                node,
                f"Node has {len(connected_inputs)} connected inputs but requires {required_inputs}.",
                "Connect the required upstream inputs or replace the node with one that matches the intended contract.",
            ))

    if len(display_nodes) == 0 and nodes:
        issues.append(_issue("warning", "missing_display_flag", None, "No display flag found in scanned nodes.", "Set display flag on the intended output node."))
    elif len(display_nodes) > 1:
        issues.append(_issue("info", "multiple_display_flags", None, "Multiple display flags found in scanned nodes.", "Confirm whether multiple visible branches are intentional."))

    if len(render_nodes) == 0 and nodes:
        issues.append(_issue("info", "missing_render_flag", None, "No render flag found in scanned nodes.", "Set render flag on the intended render/output node when applicable."))

    if not out_like_nodes and terminal_nodes:
        issues.append(_issue("warning", "missing_out_null", None, "No OUT*/null-style output marker found.", "Add or rename a final null node such as OUT for clearer downstream use."))

    issue_counts = {}
    for item in issues:
        issue_counts[item["severity"]] = issue_counts.get(item["severity"], 0) + 1

    return {
        "network_path": network_path,
        "recursive": bool(recursive),
        "scanned_node_count": len(nodes),
        "scan_truncated": truncated,
        "summary": {
            "issue_count": len(issues),
            "issue_counts_by_severity": issue_counts,
            "display_node_count": len(display_nodes),
            "render_node_count": len(render_nodes),
            "terminal_node_count": len(terminal_nodes),
            "dead_node_count": len(dead_nodes),
            "error_node_count": len(error_nodes),
            "warning_node_count": len(warning_nodes),
        },
        "display_nodes": display_nodes,
        "render_nodes": render_nodes,
        "out_like_nodes": out_like_nodes,
        "dead_nodes": dead_nodes,
        "bypassed_nodes": bypassed_nodes,
        "locked_nodes": locked_nodes,
        "error_nodes": error_nodes,
        "warning_nodes": warning_nodes,
        "missing_input_nodes": missing_input_nodes,
        "issues": issues,
    }