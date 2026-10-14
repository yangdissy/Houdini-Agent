# -*- coding: utf-8 -*-
"""Validate claims from a workflow memory against the current Houdini scene."""

import re
from typing import Any, Dict, List




_PATH_PATTERN = re.compile(r"/(?:obj|stage|out|mat|shop|ch|img|tasks)/[A-Za-z0-9_./:-]+")
_TYPE_PATTERN = re.compile(r"\(([A-Za-z_][A-Za-z0-9_:.-]*)\)")
_ATTRIBUTE_PATTERN = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")
_PARM_PATTERN = re.compile(r"\b(?:参数|parm)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)


def validate_claims(memory_text: str, inventory: Dict[str, Any]) -> Dict[str, Any]:
    text = memory_text or ""
    claims = []
    paths = set(inventory.get("paths", []))
    types = set(inventory.get("types", []))
    parms = set(inventory.get("parameters", []))
    attributes = set(inventory.get("attributes", []))
    geometry_checked = bool(inventory.get("geometry_checked"))
    for path in sorted(set(_PATH_PATTERN.findall(text))):
        claims.append({"kind": "node_path", "value": path, "status": "confirmed" if path in paths else "contradicted"})
    for node_type in sorted(set(_TYPE_PATTERN.findall(text))):
        claims.append({"kind": "node_type", "value": node_type, "status": "confirmed" if node_type in types else "contradicted"})
    for parm in sorted(set(_PARM_PATTERN.findall(text))):
        claims.append({"kind": "parameter", "value": parm, "status": "confirmed" if parm in parms else "contradicted"})
    for attribute in sorted(set(_ATTRIBUTE_PATTERN.findall(text))):
        status = "confirmed" if attribute in attributes else ("contradicted" if geometry_checked else "unknown")
        claims.append({"kind": "attribute", "value": attribute, "status": status})
    counts = {status: 0 for status in ("confirmed", "contradicted", "unknown")}
    for claim in claims:
        counts[claim["status"]] += 1
    return {"claim_count": len(claims), "status_counts": counts, "claims": claims}


def run(memory_text: str, network_path: str = "/obj", max_nodes: int = 1000) -> Dict[str, Any]:
    import hou  # type: ignore

    root = hou.node(network_path)
    if root is None:
        return {"error": f"网络不存在: {network_path}"}
    max_nodes = max(1, min(int(max_nodes), 5000))
    nodes = list(root.allSubChildren())[:max_nodes]
    inventory: Dict[str, Any] = {"paths": [], "types": [], "parameters": [], "attributes": [], "geometry_checked": False}
    for node in nodes:
        inventory["paths"].append(node.path())
        inventory["types"].append(node.type().name())
        inventory["parameters"].extend(parm.name() for parm in node.parms())
    referenced_paths = set(_PATH_PATTERN.findall(memory_text or ""))
    for path in referenced_paths:
        node = hou.node(path)
        if node is None:
            continue
        try:
            geometry = node.geometry()
            inventory["geometry_checked"] = True
            for method_name in ("pointAttribs", "vertexAttribs", "primAttribs", "globalAttribs"):
                inventory["attributes"].extend(attribute.name() for attribute in getattr(geometry, method_name)())
        except Exception:
            pass
    result = validate_claims(memory_text, inventory)
    result.update({"network_path": root.path(), "scanned_nodes": len(nodes)})
    return result