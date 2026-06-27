# -*- coding: utf-8 -*-
"""Houdini scene context inspection Skill.

Collects read-only scene state that helps the agent understand the current
working context before making or suggesting changes.
"""

SKILL_INFO = {
    "name": "inspect_scene_context",
    "description": (
        "Inspect current Houdini scene context: hip file, frame range, take, "
        "selection, common network counts, and visible UI panes. Read-only."
    ),
    "parameters": {
        "include_panes": {
            "type": "boolean",
            "description": "Whether to include visible pane tab summaries when Houdini UI is available.",
            "required": False,
            "default": True,
        },
    },
}


def _safe_call(func, default=None):
    try:
        return func()
    except Exception:
        return default


def _node_summary(node):
    return {
        "name": node.name(),
        "path": node.path(),
        "type": node.type().name(),
        "category": node.type().category().name(),
    }


def run(include_panes=True):
    """Return a compact read-only summary of the current Houdini context."""
    import hou  # type: ignore

    hip_file = {
        "path": _safe_call(lambda: hou.hipFile.path(), ""),
        "name": _safe_call(lambda: hou.hipFile.basename(), ""),
        "is_new": bool(_safe_call(lambda: hou.hipFile.isNewFile(), False)),
        "has_unsaved_changes": bool(_safe_call(lambda: hou.hipFile.hasUnsavedChanges(), False)),
    }

    frame = {
        "current": _safe_call(lambda: hou.frame(), None),
        "fps": _safe_call(lambda: hou.fps(), None),
        "playbar_range": _safe_call(lambda: list(hou.playbar.playbackRange()), None),
        "frame_range": _safe_call(lambda: list(hou.playbar.frameRange()), None),
    }

    current_take = _safe_call(lambda: hou.takes.currentTake(), None)
    take = None
    if current_take is not None:
        take = {
            "name": _safe_call(lambda: current_take.name(), ""),
            "path": _safe_call(lambda: current_take.path(), ""),
        }

    selected_nodes = [_node_summary(node) for node in _safe_call(hou.selectedNodes, ()) or ()]

    network_paths = ["/obj", "/stage", "/mat", "/shop", "/out", "/img", "/ch", "/tasks"]
    networks = []
    for path in network_paths:
        node = hou.node(path)
        if node is None:
            continue
        children = _safe_call(lambda n=node: n.children(), ()) or ()
        networks.append({
            "path": path,
            "type": node.type().name(),
            "child_count": len(children),
            "children": [_node_summary(child) for child in children[:20]],
            "truncated": len(children) > 20,
        })

    panes = []
    if include_panes and hasattr(hou, "ui"):
        for pane in _safe_call(lambda: hou.ui.paneTabs(), ()) or ():
            current_node = _safe_call(lambda p=pane: p.pwd(), None)
            pane_summary = {
                "type": str(_safe_call(lambda p=pane: p.type(), "")),
                "name": _safe_call(lambda p=pane: p.name(), ""),
            }
            if current_node is not None:
                pane_summary["pwd"] = current_node.path()
            panes.append(pane_summary)

    return {
        "hip_file": hip_file,
        "frame": frame,
        "take": take,
        "selection_count": len(selected_nodes),
        "selection": selected_nodes,
        "networks": networks,
        "panes": panes,
    }