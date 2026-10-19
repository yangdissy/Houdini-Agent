# -*- coding: utf-8 -*-
"""Build and load deterministic catalogs of node types from Houdini HOM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union


SCHEMA_VERSION = 1


def build_node_catalog(hou_module: Any) -> Dict[str, Any]:
    """Return a deterministic node catalog from the active Houdini runtime."""
    nodes = []
    for category_name, category in hou_module.nodeTypeCategories().items():
        category_key = str(category_name).lower()
        for type_name, node_type in category.nodeTypes().items():
            try:
                description = node_type.description() or ""
            except Exception:
                description = ""
            nodes.append({
                "category": category_key,
                "type_name": str(type_name),
                "description": str(description),
            })
    nodes.sort(key=lambda item: (item["category"], item["type_name"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "houdini_version": list(hou_module.applicationVersion()),
        "houdini_version_string": str(hou_module.applicationVersionString()),
        "source": "hou.nodeTypeCategories",
        "nodes": nodes,
    }


def render_node_catalog_json(catalog: Dict[str, Any]) -> str:
    """Serialize a catalog using stable formatting suitable for drift checks."""
    return json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def catalog_to_node_index(catalog: Dict[str, Any]) -> Dict[str, list]:
    """Convert a catalog to the tuple index consumed by HoudiniMCP."""
    index: Dict[str, list] = {}
    for node in catalog.get("nodes", []):
        category = node["category"]
        type_name = node["type_name"]
        index.setdefault(category, []).append((
            type_name,
            node.get("description", ""),
            f"{category}/{type_name}",
        ))
    return index


def load_node_catalog(
    path: Union[str, Path],
    expected_houdini_version: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Load a catalog, rejecting unknown schemas and runtime version mismatch."""
    catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    if catalog.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported node catalog schema: {catalog.get('schema_version')!r}"
        )
    if expected_houdini_version is not None:
        actual = tuple(catalog.get("houdini_version", ()))
        expected = tuple(expected_houdini_version)
        if actual != expected:
            raise ValueError(
                f"Houdini version mismatch: catalog={actual}, expected={expected}"
            )
    return catalog
