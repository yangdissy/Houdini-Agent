# -*- coding: utf-8 -*-
"""Cache/export node reporting Skill."""

import os
import re


SKILL_INFO = {
    "name": "cache_node_report",
    "description": (
        "Scan cache and export nodes, report output paths, frame ranges, disk existence, "
        "and modified times. Read-only; does not cook or write caches."
    ),
    "parameters": {
        "root_path": {
            "type": "string",
            "description": "Root network path to scan, for example /obj, /out, or /. Defaults to /.",
            "required": False,
            "default": "/",
        },
        "recursive": {
            "type": "boolean",
            "description": "Whether to scan all descendants. Defaults to true.",
            "required": False,
            "default": True,
        },
        "check_disk": {
            "type": "boolean",
            "description": "Whether to check matching files on disk. Defaults to true.",
            "required": False,
            "default": True,
        },
        "max_nodes": {
            "type": "integer",
            "description": "Maximum nodes to inspect before truncating. Defaults to 3000.",
            "required": False,
            "default": 3000,
        },
    },
}


_CACHE_TYPE_HINTS = (
    "filecache",
    "dopio",
    "rop_geometry",
    "geometry",
    "alembic",
    "usd",
    "usdrop",
    "karma",
    "mantra",
    "ifd",
    "comp",
    "fetch",
)

_PATH_PARAM_HINTS = (
    "file",
    "sopoutput",
    "lopoutput",
    "output",
    "picture",
    "vm_picture",
    "filename",
    "filepath",
    "usdfile",
    "abcfile",
)

_FRAME_PARAM_NAMES = (
    "f1",
    "f2",
    "f3",
    "trange",
    "range",
    "startframe",
    "endframe",
)


def _safe_call(func, default=None):
    try:
        return func()
    except Exception:
        return default


def _node_info(node):
    return {
        "name": node.name(),
        "path": node.path(),
        "type": _safe_call(lambda: node.type().name(), "") or "",
        "category": _safe_call(lambda: node.type().category().name(), "") or "",
    }


def _is_cache_node(node):
    info = _node_info(node)
    type_name = info["type"].lower()
    name = info["name"].lower()
    category = info["category"].lower()
    return (
        any(hint in type_name for hint in _CACHE_TYPE_HINTS)
        or any(hint in name for hint in ("cache", "export", "rop", "write"))
        or category in ("driver", "rop")
    )


def _parm_string(parm):
    value = _safe_call(lambda: parm.eval(), "")
    if isinstance(value, str):
        return value.strip()
    return ""


def _looks_like_output_path(value):
    if not value:
        return False
    lowered = value.lower()
    return (
        "/" in value
        or "\\" in value
        or "$hip" in lowered
        or "$job" in lowered
        or "$temp" in lowered
        or re.search(r"\.(bgeo|sc|abc|usd|usdc|usda|vdb|exr|png|jpg|jpeg|tif|tiff|hip|ifd)\b", lowered) is not None
    )


def _path_pattern(path):
    pattern = re.sub(r"\$F\d*", "*", path)
    pattern = re.sub(r"#+", "*", pattern)
    return pattern


def _disk_status(path):
    import glob

    expanded = os.path.expandvars(path)
    pattern = _path_pattern(expanded)
    has_glob = any(token in pattern for token in "*?[")
    matches = sorted(glob.glob(pattern)) if has_glob else ([expanded] if os.path.exists(expanded) else [])
    sample = matches[:10]
    latest_mtime = None
    latest_path = None
    for match in matches:
        try:
            mtime = os.path.getmtime(match)
        except OSError:
            continue
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime = mtime
            latest_path = match
    return {
        "exists": bool(matches),
        "match_count": len(matches),
        "sample": sample,
        "latest_path": latest_path,
        "latest_mtime": latest_mtime,
    }


def _collect_nodes(root, recursive, max_nodes):
    if recursive:
        nodes = list(_safe_call(lambda: root.allSubChildren(), ()) or ())
    else:
        nodes = list(_safe_call(lambda: root.children(), ()) or ())
    truncated = len(nodes) > max_nodes
    return nodes[:max_nodes], truncated


def _collect_path_parameters(node):
    paths = []
    for parm in _safe_call(lambda: node.parms(), ()) or ():
        parm_name = _safe_call(lambda p=parm: p.name(), "") or ""
        label = _safe_call(lambda p=parm: p.description(), "") or ""
        value = _parm_string(parm)
        combined = f"{parm_name} {label}".lower()
        if value and _looks_like_output_path(value) and any(hint in combined for hint in _PATH_PARAM_HINTS):
            paths.append({"parm": parm_name, "label": label, "path": value})
    return paths


def _collect_frame_parameters(node):
    frames = {}
    for name in _FRAME_PARAM_NAMES:
        parm = _safe_call(lambda n=node, parm_name=name: n.parm(parm_name), None)
        if parm is not None:
            frames[name] = _safe_call(lambda p=parm: p.eval(), None)
    return frames


def run(root_path="/", recursive=True, check_disk=True, max_nodes=3000):
    """Report cache/export nodes and their output files without writing anything."""
    import hou  # type: ignore

    root = hou.node(root_path)
    if not root:
        return {"error": f"Root network does not exist: {root_path}"}

    max_nodes = max(1, min(int(max_nodes), 10000))
    nodes, truncated = _collect_nodes(root, bool(recursive), max_nodes)
    cache_nodes = []
    missing_outputs = []
    path_count = 0

    for node in nodes:
        if not _is_cache_node(node):
            continue
        info = _node_info(node)
        path_parameters = _collect_path_parameters(node)
        frame_parameters = _collect_frame_parameters(node)
        if check_disk:
            for item in path_parameters:
                item["disk"] = _disk_status(item["path"])
                if not item["disk"]["exists"]:
                    missing_outputs.append({**info, "parm": item["parm"], "path": item["path"]})
        path_count += len(path_parameters)
        cache_nodes.append({
            **info,
            "path_parameters": path_parameters,
            "frame_parameters": frame_parameters,
            "has_output_path": bool(path_parameters),
            "bypassed": bool(_safe_call(lambda n=node: n.isBypassed(), False)) if hasattr(node, "isBypassed") else False,
        })

    nodes_without_paths = [node for node in cache_nodes if not node["has_output_path"]]
    return {
        "root_path": root_path,
        "recursive": bool(recursive),
        "check_disk": bool(check_disk),
        "scanned_node_count": len(nodes),
        "scan_truncated": truncated,
        "summary": {
            "cache_node_count": len(cache_nodes),
            "output_path_count": path_count,
            "nodes_without_output_paths": len(nodes_without_paths),
            "missing_output_count": len(missing_outputs),
        },
        "cache_nodes": cache_nodes,
        "nodes_without_output_paths": nodes_without_paths,
        "missing_outputs": missing_outputs,
    }