# -*- coding: utf-8 -*-
"""Stable external MCP manifest and runtime capability helpers."""

from __future__ import annotations

import json
import importlib.util
from typing import Dict, Iterable, List, Optional, Set


def build_external_tool_manifest(
    registry,
    dispatch: Dict[str, str],
    allowed_tools: Iterable[str],
    denied_tools: Optional[Iterable[str]] = None,
) -> List[dict]:
    """Build bounded metadata for executable external Registry entries."""
    allowed: Set[str] = set(allowed_tools or ())
    denied: Set[str] = set(denied_tools or ())
    manifest = []
    for tool_name in sorted(allowed - denied - {"health"}):
        meta = registry.get_meta(tool_name)
        handler_name = dispatch.get(tool_name)
        if meta is None or not meta.enabled or not meta.external_mcp_visible:
            continue
        if meta.runtime != "houdini" or "ask" not in meta.modes or not handler_name:
            continue
        tags = set(meta.tags or ())
        manifest.append({
            "name": tool_name,
            "runtime": meta.runtime,
            "risk_level": meta.risk_level,
            "readonly": "readonly" in tags,
            "mutating": bool(meta.mutating),
            "handler": handler_name,
            "long_running": "long_running" in tags,
            "feature": next((tag.split(":", 1)[1] for tag in tags if tag.startswith("feature:")), None),
            "minimum_houdini_version": next((
                tag.split(":", 1)[1] for tag in tags if tag.startswith("houdini_min:")
            ), None),
        })
    return manifest


def render_external_manifest_json(manifest: List[dict]) -> str:
    """Render deterministic committed manifest content."""
    payload = {"schema_version": 1, "tools": list(manifest)}
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_runtime_capabilities(
    manifest: List[dict],
    dispatcher,
    executor,
    hou_module,
    agent_version: str,
    sdk_version: Optional[str],
    session_id: str,
) -> dict:
    """Inspect runtime capability facts without executing a tool."""
    degradations = []
    houdini_version = None
    if hou_module is None:
        degradations.append("houdini_unavailable")
    else:
        try:
            houdini_version = str(hou_module.applicationVersionString())
        except Exception:
            degradations.append("houdini_version_unavailable")

    if not sdk_version:
        degradations.append("mcp_sdk_version_unavailable")

    if executor is None:
        executor_state = "unavailable"
        degradations.append("executor_unavailable")
    else:
        try:
            if executor.is_shutdown():
                executor_state = "shutdown"
            elif executor.is_blocked():
                executor_state = "blocked"
            else:
                executor_state = "ready"
        except Exception:
            executor_state = "unavailable"
        if executor_state != "ready":
            degradations.append(f"executor_{executor_state}")

    available_tools = []
    unavailable_tools = []

    def version_tuple(value):
        try:
            return tuple(int(part) for part in str(value).split("."))
        except (TypeError, ValueError):
            return None

    for item in sorted((manifest or [])[:200], key=lambda value: value.get("name", "")):
        name = str(item.get("name") or "")
        handler_name = str(item.get("handler") or "")
        if not name or not handler_name or not callable(getattr(dispatcher, handler_name, None)):
            unavailable_tools.append({"name": name, "reason": "handler_unavailable"})
            continue
        feature = item.get("feature")
        if feature:
            try:
                feature_available = importlib.util.find_spec(str(feature)) is not None
            except Exception:
                feature_available = False
            if not feature_available:
                unavailable_tools.append({"name": name, "reason": f"feature_unavailable:{feature}"})
                continue
        minimum_version = item.get("minimum_houdini_version")
        if minimum_version:
            current = version_tuple(houdini_version)
            required = version_tuple(minimum_version)
            if current is None or required is None or current < required:
                unavailable_tools.append({
                    "name": name, "reason": f"houdini_version_too_old:{minimum_version}",
                })
                continue
        available_tools.append(name)

    if unavailable_tools:
        degradations.append("tool_capability_mismatch")
    return {
        "status": "healthy" if not degradations else "degraded",
        "session_id": session_id,
        "houdini_version": houdini_version,
        "agent_version": agent_version,
        "mcp_sdk_version": sdk_version,
        "executor_state": executor_state,
        "available_tools": available_tools,
        "unavailable_tools": unavailable_tools,
        "degradations": sorted(set(degradations)),
        "manifest_truncated": len(manifest or []) > 200,
    }


def build_connection_status(running: bool, capabilities: Optional[dict]) -> dict:
    """Classify connection state from bounded runtime facts."""
    if not running:
        return {"state": "not_started", "running": False, "degradations": []}
    degradations = list((capabilities or {}).get("degradations") or [])
    if "mcp_sdk_version_unavailable" in degradations:
        state = "sdk_missing"
    elif "houdini_unavailable" in degradations or "houdini_version_unavailable" in degradations:
        state = "houdini_unavailable"
    elif any(item in degradations for item in (
        "executor_blocked", "executor_shutdown", "executor_unavailable"
    )):
        executor_state = str((capabilities or {}).get("executor_state") or "blocked")
        state = f"executor_{executor_state}"
    elif "tool_capability_mismatch" in degradations:
        state = "capability_missing"
    else:
        state = "connected"
    return {"state": state, "running": True, "degradations": sorted(set(degradations))}
