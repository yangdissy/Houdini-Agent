# -*- coding: utf-8 -*-
"""Bounded, read-only TOP/PDG inspection helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List


def _load_pdg():
    try:
        import pdg  # type: ignore
        return pdg
    except Exception:
        return None


def _safe_call(call, default=None):
    try:
        return call()
    except Exception:
        return default


def _value(owner, name: str, default=None):
    value = _safe_call(lambda: getattr(owner, name), default)
    if callable(value):
        return _safe_call(value, default)
    return value


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(item) for item in value]
        return str(value)


def _state_name(item) -> str:
    state = _value(item, "state", None)
    name = _value(state, "name", None)
    return str(name if name is not None else state)


def _work_items(pdg_node) -> List[Any]:
    return list(_value(pdg_node, "workItems", ()) or ())


def _resolve_pdg_node(top_node):
    return _safe_call(lambda: top_node.getPDGNode(), None) if top_node is not None else None


def inspect_top_network(top_node, pdg_module=None) -> Dict[str, Any]:
    """Summarize current TOP graph state without scheduling or cooking."""
    pdg_module = pdg_module or _load_pdg()
    if pdg_module is None:
        return {"success": False, "error_code": "pdg_unavailable", "error": "PDG module is unavailable"}
    if top_node is None:
        return {"success": False, "error_code": "top_node_unavailable", "error": "TOP node is unavailable"}

    pdg_node = _resolve_pdg_node(top_node)
    if pdg_node is None:
        return {"success": False, "error_code": "pdg_node_unavailable", "error": "Node has no PDG node"}
    context = _safe_call(lambda: top_node.getPDGGraphContext(), None)
    graph = _value(context, "graph", None) if context is not None else None
    graph_nodes = list(_value(graph, "nodes", ()) or ()) if graph is not None else [pdg_node]
    scheduler = _safe_call(lambda: top_node.schedulerNode(), None)

    state_counts: Dict[str, int] = {}
    work_item_count = 0
    for graph_node in graph_nodes[:1000]:
        for item in _work_items(graph_node)[:100000]:
            state = _state_name(item)
            state_counts[state] = state_counts.get(state, 0) + 1
            work_item_count += 1

    return {
        "success": True,
        "data": {
            "node_path": str(_safe_call(lambda: top_node.path(), "")),
            "pdg_node_name": str(_value(pdg_node, "name", "")),
            "scheduler_path": str(_safe_call(lambda: scheduler.path(), "")) if scheduler else "",
            "pdg_node_count": len(graph_nodes),
            "work_item_count": work_item_count,
            "state_counts": state_counts,
            "truncated": len(graph_nodes) > 1000,
        },
    }


def list_work_items(top_node, start: int = 0, count: int = 100,
                    max_attributes: int = 50, max_output_files: int = 50,
                    payload_limit_bytes: int = 256 * 1024,
                    pdg_module=None) -> Dict[str, Any]:
    """Return one bounded page of work item state and output metadata."""
    pdg_module = pdg_module or _load_pdg()
    if pdg_module is None:
        return {"success": False, "error_code": "pdg_unavailable", "error": "PDG module is unavailable"}
    if top_node is None:
        return {"success": False, "error_code": "top_node_unavailable", "error": "TOP node is unavailable"}
    pdg_node = _resolve_pdg_node(top_node)
    if pdg_node is None:
        return {"success": False, "error_code": "pdg_node_unavailable", "error": "Node has no PDG node"}

    start = max(0, int(start))
    requested_count = int(count)
    page_limit = max(1, min(requested_count, 500))
    max_attributes = max(0, min(int(max_attributes), 100))
    max_output_files = max(0, min(int(max_output_files), 100))
    payload_limit_bytes = max(1024, min(int(payload_limit_bytes), 1024 * 1024))
    all_items = _work_items(pdg_node)
    result_items = []
    payload_bytes = 0

    for item in all_items[start:start + page_limit]:
        attributes = []
        for attrib in list(_value(item, "attribs", ()) or ())[:max_attributes]:
            attributes.append({
                "name": str(_value(attrib, "name", "")),
                "value": _jsonable(_value(attrib, "value", None)),
            })
        output_files = []
        for output_file in list(_value(item, "outputFiles", ()) or ())[:max_output_files]:
            output_files.append({
                "path": str(_value(output_file, "path", "")),
                "tag": str(_value(output_file, "tag", "")),
            })
        row = {
            "index": int(_value(item, "index", -1)),
            "name": str(_value(item, "name", "")),
            "state": _state_name(item),
            "attributes": attributes,
            "output_files": output_files,
        }
        row_bytes = len(json.dumps(row, ensure_ascii=False, default=str).encode("utf-8"))
        if result_items and payload_bytes + row_bytes > payload_limit_bytes:
            break
        result_items.append(row)
        payload_bytes += row_bytes

    next_start = start + len(result_items)
    truncated = next_start < len(all_items)
    return {
        "success": True,
        "data": {
            "node_path": str(_safe_call(lambda: top_node.path(), "")),
            "start": start,
            "requested_count": requested_count,
            "page_limit": page_limit,
            "count": len(result_items),
            "total_count": len(all_items),
            "items": result_items,
            "payload_bytes": payload_bytes,
            "payload_limit_bytes": payload_limit_bytes,
            "truncated": truncated,
            "next_start": next_start if truncated else None,
        },
    }


def get_top_errors(top_node, start: int = 0, count: int = 100,
                   payload_limit_bytes: int = 256 * 1024,
                   pdg_module=None) -> Dict[str, Any]:
    """Return bounded failed-item metadata without reading log contents."""
    pdg_module = pdg_module or _load_pdg()
    if pdg_module is None:
        return {"success": False, "error_code": "pdg_unavailable", "error": "PDG module is unavailable"}
    if top_node is None:
        return {"success": False, "error_code": "top_node_unavailable", "error": "TOP node is unavailable"}
    pdg_node = _resolve_pdg_node(top_node)
    if pdg_node is None:
        return {"success": False, "error_code": "pdg_node_unavailable", "error": "Node has no PDG node"}

    start = max(0, int(start))
    requested_count = int(count)
    page_limit = max(1, min(requested_count, 500))
    payload_limit_bytes = max(1024, min(int(payload_limit_bytes), 1024 * 1024))
    failed_items = [
        item for item in _work_items(pdg_node)
        if "fail" in _state_name(item).lower() or "error" in _state_name(item).lower()
    ]
    errors = []
    payload_bytes = 0
    for item in failed_items[start:start + page_limit]:
        row = {
            "index": int(_value(item, "index", -1)),
            "name": str(_value(item, "name", "")),
            "state": _state_name(item),
            "error": str(_value(item, "errorMessage", "")),
            "command": str(_value(item, "command", "")),
            "log_path": str(_value(item, "logFile", "")),
        }
        row_bytes = len(json.dumps(row, ensure_ascii=False, default=str).encode("utf-8"))
        if errors and payload_bytes + row_bytes > payload_limit_bytes:
            break
        errors.append(row)
        payload_bytes += row_bytes

    next_start = start + len(errors)
    truncated = next_start < len(failed_items)
    return {
        "success": True,
        "data": {
            "node_path": str(_safe_call(lambda: top_node.path(), "")),
            "start": start,
            "requested_count": requested_count,
            "page_limit": page_limit,
            "count": len(errors),
            "total_failed_count": len(failed_items),
            "errors": errors,
            "payload_bytes": payload_bytes,
            "payload_limit_bytes": payload_limit_bytes,
            "truncated": truncated,
            "next_start": next_start if truncated else None,
        },
    }