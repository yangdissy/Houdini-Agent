# -*- coding: utf-8 -*-
"""Bounded, read-only USD inspection helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional


def _safe_call(call, default=None):
    try:
        return call()
    except Exception:
        return default


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


def _load_usd_shade():
    try:
        from pxr import UsdShade  # type: ignore
        return UsdShade
    except Exception:
        return None


def _load_usd():
    try:
        from pxr import Usd  # type: ignore
        return Usd
    except Exception:
        return None


def _append_bounded(items: List[dict], item: dict, current_bytes: int,
                    payload_limit_bytes: int) -> tuple:
    item_bytes = len(json.dumps(item, ensure_ascii=False, default=str).encode("utf-8"))
    if items and current_bytes + item_bytes > payload_limit_bytes:
        return current_bytes, False
    items.append(item)
    return current_bytes + item_bytes, True


def _layer_info(layer, max_sublayers: int) -> dict:
    sub_layers = list(_safe_call(lambda: layer.subLayerPaths, ()) or ())
    return {
        "identifier": str(_safe_call(lambda: layer.identifier, "")),
        "real_path": str(_safe_call(lambda: layer.realPath, "")),
        "anonymous": bool(_safe_call(lambda: layer.anonymous, False)),
        "dirty": bool(_safe_call(lambda: layer.dirty, False)),
        "sub_layers": [str(path) for path in sub_layers[:max_sublayers]],
        "sub_layers_truncated": len(sub_layers) > max_sublayers,
    }


def inspect_usd_layer_stack(stage, max_layers: int = 100,
                            max_sublayers: int = 100,
                            payload_limit_bytes: int = 256 * 1024) -> Dict[str, Any]:
    """Inspect composed stage layers without opening, muting, or editing layers."""
    if stage is None:
        return {"success": False, "error_code": "stage_unavailable", "error": "USD stage is unavailable"}
    max_layers = max(1, min(int(max_layers), 500))
    max_sublayers = max(0, min(int(max_sublayers), 500))
    payload_limit_bytes = max(1024, min(int(payload_limit_bytes), 1024 * 1024))
    root_layer = _safe_call(lambda: stage.GetRootLayer(), None)
    session_layer = _safe_call(lambda: stage.GetSessionLayer(), None)
    layers = list(_safe_call(lambda: stage.GetLayerStack(True), ()) or ())
    muted = [str(value) for value in (_safe_call(lambda: stage.GetMutedLayers(), ()) or ())]

    entries = []
    payload_bytes = 0
    truncated = False
    for layer in layers[:max_layers]:
        item = _layer_info(layer, max_sublayers)
        payload_bytes, appended = _append_bounded(
            entries, item, payload_bytes, payload_limit_bytes
        )
        if not appended:
            truncated = True
            break
        if item["sub_layers_truncated"]:
            truncated = True
    if len(layers) > max_layers:
        truncated = True

    data = {
        "root_layer": _layer_info(root_layer, max_sublayers) if root_layer else None,
        "session_layer": _layer_info(session_layer, max_sublayers) if session_layer else None,
        "muted_layers": muted[:max_layers],
        "layers": entries,
        "layer_count": len(layers),
        "payload_bytes": payload_bytes,
        "payload_limit_bytes": payload_limit_bytes,
        "truncated": truncated or len(muted) > max_layers,
    }
    return {"success": True, "data": data}


def inspect_usd_prim(stage, prim_path: str,
                     attribute_names: Optional[Iterable[str]] = None,
                     max_attributes: int = 100, max_metadata: int = 100,
                     max_prim_stack: int = 100,
                     payload_limit_bytes: int = 256 * 1024,
                     binding_purpose: str = "allPurpose",
                     usd_shade=None, usd_module=None) -> Dict[str, Any]:
    """Inspect one composed prim without authoring or loading payloads."""
    usd_shade = usd_shade or _load_usd_shade()
    usd_module = usd_module or _load_usd()
    if usd_shade is None:
        return {
            "success": False,
            "error_code": "pxr_unavailable",
            "error": "USD pxr.UsdShade is unavailable",
        }
    if stage is None:
        return {"success": False, "error_code": "stage_unavailable", "error": "USD stage is unavailable"}
    if not prim_path:
        return {"success": False, "error_code": "prim_path_required", "error": "prim_path is required"}

    prim = _safe_call(lambda: stage.GetPrimAtPath(prim_path), None)
    if prim is None or not bool(_safe_call(lambda: prim.IsValid(), False)):
        return {
            "success": False,
            "error_code": "prim_not_found",
            "error": f"USD prim does not exist: {prim_path}",
        }

    max_attributes = max(0, min(int(max_attributes), 500))
    max_metadata = max(0, min(int(max_metadata), 500))
    max_prim_stack = max(0, min(int(max_prim_stack), 500))
    payload_limit_bytes = max(1024, min(int(payload_limit_bytes), 1024 * 1024))
    requested_names = [str(name) for name in (attribute_names or []) if str(name).strip()]
    all_attributes = list(_safe_call(lambda: prim.GetAttributes(), ()) or ())
    available = {
        str(_safe_call(lambda item=item: item.GetName(), "")): item
        for item in all_attributes
    }
    selected_names = requested_names or sorted(name for name in available if name)
    missing = [name for name in selected_names if name not in available]

    attributes = []
    payload_bytes = 0
    truncated = False
    for name in selected_names[:max_attributes]:
        attribute = available.get(name)
        if attribute is None:
            continue
        item = {
            "name": name,
            "type": str(_safe_call(lambda: attribute.GetTypeName(), "")),
            "authored": bool(_safe_call(lambda: attribute.HasAuthoredValueOpinion(), False)),
            "value": _jsonable(_safe_call(lambda: attribute.Get(), None)),
        }
        payload_bytes, appended = _append_bounded(
            attributes, item, payload_bytes, payload_limit_bytes
        )
        if not appended:
            truncated = True
            break
    if len(selected_names) > max_attributes:
        truncated = True

    metadata = []
    all_metadata = _safe_call(lambda: prim.GetAllMetadata(), {}) or {}
    for key in sorted(all_metadata)[:max_metadata]:
        item = {"name": str(key), "value": _jsonable(all_metadata[key])}
        payload_bytes, appended = _append_bounded(
            metadata, item, payload_bytes, payload_limit_bytes
        )
        if not appended:
            truncated = True
            break
    if len(all_metadata) > max_metadata:
        truncated = True

    prim_stack = []
    stack = list(_safe_call(lambda: prim.GetPrimStack(), ()) or ())
    for spec in stack[:max_prim_stack]:
        layer = _safe_call(lambda spec=spec: spec.layer, None)
        item = {
            "path": str(_safe_call(lambda spec=spec: spec.path, "")),
            "layer": str(_safe_call(lambda layer=layer: layer.identifier, "")) if layer else "",
        }
        payload_bytes, appended = _append_bounded(
            prim_stack, item, payload_bytes, payload_limit_bytes
        )
        if not appended:
            truncated = True
            break
    if len(stack) > max_prim_stack:
        truncated = True

    composition_arcs = []
    if usd_module is not None:
        query = _safe_call(lambda: usd_module.PrimCompositionQuery(prim), None)
        arcs = list(_safe_call(lambda: query.GetCompositionArcs(), ()) or ()) if query else []
        for arc in arcs[:max_prim_stack]:
            item = {
                "type": str(_safe_call(lambda arc=arc: arc.arcType, "")),
                "target": str(_safe_call(lambda arc=arc: arc.targetNode, "")),
            }
            payload_bytes, appended = _append_bounded(
                composition_arcs, item, payload_bytes, payload_limit_bytes
            )
            if not appended:
                truncated = True
                break
        if len(arcs) > max_prim_stack:
            truncated = True

    binding = None
    try:
        purpose = getattr(usd_shade.Tokens, binding_purpose, binding_purpose)
        material, relationship = usd_shade.MaterialBindingAPI(prim).ComputeBoundMaterial(purpose)
        material_path = str(material.GetPath()) if material else ""
        if material_path:
            binding = {
                "purpose": binding_purpose,
                "material_path": material_path,
                "relationship": str(relationship) if relationship else "",
            }
    except Exception:
        binding = None

    data = {
        "path": str(_safe_call(lambda: prim.GetPath(), prim_path)),
        "type": str(_safe_call(lambda: prim.GetTypeName(), "")),
        "active": bool(_safe_call(lambda: prim.IsActive(), False)),
        "loaded": bool(_safe_call(lambda: prim.IsLoaded(), False)),
        "defined": bool(_safe_call(lambda: prim.IsDefined(), False)),
        "instance": bool(_safe_call(lambda: prim.IsInstance(), False)),
        "attributes": attributes,
        "metadata": metadata,
        "prim_stack": prim_stack,
        "composition_arcs": composition_arcs,
        "material_binding": binding,
        "payload_bytes": payload_bytes,
        "payload_limit_bytes": payload_limit_bytes,
        "truncated": truncated,
    }
    if missing:
        data["missing_attributes"] = missing
    return {"success": True, "data": data}