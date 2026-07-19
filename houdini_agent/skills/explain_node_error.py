# -*- coding: utf-8 -*-
"""Single-node error diagnosis Skill (borrowed from fxhoudinimcp get_node_errors_detailed).

Read-only, focused counterpart to the existing whole-network validators
(`verify_network` / `validate_network_contract`). Those list errors across an
entire network; this drills into ONE node's errors/warnings and, crucially,
surfaces the *suspect parameters* most likely to be the cause — e.g. a file /
path parameter pointing at a file that does not exist on disk. That last check
is the piece our current tooling lacks.

Does NOT modify the scene. Optionally force-cooks the node to make upstream
errors surface (default on), which is a read-only diagnostic cook.
"""

import os

SKILL_INFO = {
    "name": "explain_node_error",
    "category": "scene",
    "description": (
        "Diagnose ONE node's errors/warnings in depth and pinpoint the suspect parameters "
        "(especially file/path parameters pointing at missing files on disk). Read-only. "
        "Use when a specific node reports an error and you need to find the root cause fast — "
        "for whole-network health use verify_network / validate_network_contract instead."
    ),
    "risk_level": "low",
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "Path of the node to diagnose, e.g. '/obj/geo1/file1'.",
            "required": True,
        },
        "cook": {
            "type": "boolean",
            "description": "Force a read-only cook first so upstream errors surface. Default true. "
                           "Set false on heavy nodes to only read already-present errors.",
            "required": False,
            "default": True,
        },
    },
}


def _safe(func, default=None):
    try:
        return func()
    except Exception:
        return default


def _is_file_param(parm):
    """Best-effort detection of a file/path string parameter."""
    tmpl = _safe(lambda: parm.parmTemplate(), None)
    if tmpl is None:
        return False
    import hou  # type: ignore

    if _safe(lambda: tmpl.type(), None) != hou.parmTemplateType.String:
        return False
    tags = _safe(lambda: tmpl.tags(), {}) or {}
    if tags.get("filechooser_mode") is not None:
        return True
    if _safe(lambda: tmpl.stringType(), None) == hou.stringParmType.FileReference:
        return True
    return "file" in _safe(lambda: parm.name(), "").lower()


def _suspect_parms(node):
    """Return file/path parameters whose evaluated value points at a missing file."""
    suspects = []
    parms = _safe(lambda: node.parms(), ()) or ()
    for parm in parms:
        if not _is_file_param(parm):
            continue
        value = _safe(lambda p=parm: p.eval(), None)
        if not value or not isinstance(value, str):
            continue
        # Skip values that still contain unresolved Houdini variables.
        expanded = _safe(lambda v=value: __import__("hou").text.expandString(v), value)
        exists = _safe(lambda e=expanded: os.path.isfile(e), None)
        if exists is False:
            suspects.append({
                "parm": _safe(lambda p=parm: p.name(), ""),
                "value": value,
                "expanded": expanded,
                "reason": "file does not exist on disk",
            })
    return suspects


def run(node_path, cook=True):
    """Diagnose a single node's errors and likely-culprit parameters. Read-only."""
    if not node_path or not str(node_path).strip():
        return {"error": "node_path is required."}

    import hou  # type: ignore

    node = hou.node(node_path)
    if not node:
        return {"error": f"Node does not exist: {node_path}"}

    if cook:
        # Read-only diagnostic cook: makes upstream errors surface. Non-forced
        # to avoid needless recook of an already-cooked heavy node.
        _safe(lambda: node.cook(force=False))

    errors = [str(e) for e in (_safe(lambda: node.errors(), []) or [])]
    warnings = [str(w) for w in (_safe(lambda: node.warnings(), []) or [])]

    result = {
        "node_path": node.path(),
        "type": _safe(lambda: node.type().name(), ""),
        "has_errors": bool(errors),
        "has_warnings": bool(warnings),
        "errors": errors,
        "warnings": warnings,
    }

    if errors or warnings:
        result["suspect_parameters"] = _suspect_parms(node)

    # Report connected input state — a common cause of "node has no input" errors.
    inputs = _safe(lambda: node.inputs(), ()) or ()
    result["inputs"] = [
        {"index": i, "connected": inp is not None,
         "source": _safe(lambda n=inp: n.path(), None) if inp is not None else None}
        for i, inp in enumerate(inputs)
    ]

    return result
