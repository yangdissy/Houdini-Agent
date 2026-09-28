# -*- coding: utf-8 -*-
"""LOP/USD stage inspection Skill."""

from houdini_agent.utils.usd_inspection import inspect_usd_layer_stack

SKILL_INFO = {
    "name": "inspect_lop_stage",
    "category": "usd",
    "description": (
        "Inspect a LOP node's USD stage: layers, prim type counts, cameras, "
        "lights, material-binding candidates, payloads, and references. Read-only."
    ),
    "risk_level": "low",
    "parameters": {
        "node_path": {
            "type": "string",
            "description": "LOP node path, for example /stage/OUT.",
            "required": True,
        },
        "max_prims": {
            "type": "integer",
            "description": "Maximum prims to inspect before truncating. Defaults to 5000.",
            "required": False,
            "default": 5000,
        },
    },
}


def _safe_call(func, default=None):
    try:
        return func()
    except Exception:
        return default


def _metadata_list(prim, key):
    value = _safe_call(lambda: prim.GetMetadata(key), None)
    if not value:
        return []
    return [str(value)] if not isinstance(value, (list, tuple)) else [str(item) for item in value]


def run(node_path, max_prims=5000):
    """Inspect the USD stage produced by a LOP node."""
    import hou  # type: ignore

    node = hou.node(node_path)
    if not node:
        return {"error": f"Node does not exist: {node_path}"}
    if not hasattr(node, "stage"):
        return {"error": f"Node is not a LOP node or has no stage() method: {node_path}"}

    stage = _safe_call(lambda: node.stage(), None)
    if stage is None:
        return {"error": f"Could not read USD stage from {node_path}"}

    max_prims = max(1, min(int(max_prims), 50000))
    layer_result = inspect_usd_layer_stack(stage)
    layer_data = layer_result.get("data", {}) if layer_result.get("success") else {}
    root_layer = layer_data.get("root_layer") or {}
    session_layer = layer_data.get("session_layer") or {}
    prims = []
    type_counts = {}
    cameras = []
    lights = []
    material_binding_candidates = []
    reference_candidates = []
    payload_candidates = []
    truncated = False

    for index, prim in enumerate(stage.Traverse()):
        if index >= max_prims:
            truncated = True
            break
        type_name = _safe_call(lambda p=prim: p.GetTypeName(), "") or ""
        path = str(_safe_call(lambda p=prim: p.GetPath(), ""))
        type_counts[type_name or "<typeless>"] = type_counts.get(type_name or "<typeless>", 0) + 1
        active = bool(_safe_call(lambda p=prim: p.IsActive(), True))
        loaded = bool(_safe_call(lambda p=prim: p.IsLoaded(), True))
        defined = bool(_safe_call(lambda p=prim: p.IsDefined(), True))

        if len(prims) < 100:
            prims.append({
                "path": path,
                "type": type_name,
                "active": active,
                "loaded": loaded,
                "defined": defined,
            })

        lowered_type = type_name.lower()
        if "camera" in lowered_type:
            cameras.append(path)
        if "light" in lowered_type:
            lights.append(path)

        relationships = _safe_call(lambda p=prim: p.GetRelationships(), ()) or ()
        relationship_names = [_safe_call(lambda rel=rel: rel.GetName(), "") for rel in relationships]
        if any("material" in name.lower() for name in relationship_names if name):
            material_binding_candidates.append(path)

        references = _metadata_list(prim, "references")
        payloads = _metadata_list(prim, "payload") or _metadata_list(prim, "payloads")
        if references:
            reference_candidates.append({"path": path, "metadata": references[:5]})
        if payloads:
            payload_candidates.append({"path": path, "metadata": payloads[:5]})

    return {
        "node_path": node_path,
        "root_layer": root_layer.get("identifier", ""),
        "session_layer": session_layer.get("identifier", ""),
        "sub_layers": list(root_layer.get("sub_layers", [])),
        "layer_stack": layer_data,
        "inspected_prim_count": sum(type_counts.values()),
        "truncated": truncated,
        "type_counts": type_counts,
        "prim_sample": prims,
        "cameras": cameras[:100],
        "lights": lights[:100],
        "material_binding_candidates": material_binding_candidates[:200],
        "reference_candidates": reference_candidates[:100],
        "payload_candidates": payload_candidates[:100],
    }