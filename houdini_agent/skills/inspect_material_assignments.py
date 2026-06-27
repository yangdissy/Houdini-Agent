# -*- coding: utf-8 -*-
"""Material assignment inspection Skill."""

SKILL_INFO = {
    "name": "inspect_material_assignments",
    "description": (
        "Scan material libraries and material-like parameter references to find "
        "assigned, missing, and unused material paths. Read-only."
    ),
    "parameters": {
        "root_path": {
            "type": "string",
            "description": "Root network to scan, usually /, /obj, or /stage. Defaults to /.",
            "required": False,
            "default": "/",
        },
        "max_nodes": {
            "type": "integer",
            "description": "Maximum scanned nodes to avoid huge scene dumps. Defaults to 2000.",
            "required": False,
            "default": 2000,
        },
    },
}


_MATERIAL_PARAM_HINTS = (
    "material",
    "shop_materialpath",
    "materialpath",
    "shop_surfacepath",
    "shop_displacepath",
)

_MATERIAL_NODE_CATEGORIES = {"Vop", "Shop", "Material"}


def _safe_call(func, default=None):
    try:
        return func()
    except Exception:
        return default


def _node_type_name(node):
    return _safe_call(lambda: node.type().name(), "") or ""


def _node_category_name(node):
    return _safe_call(lambda: node.type().category().name(), "") or ""


def _is_material_node(node):
    path = node.path()
    type_name = _node_type_name(node).lower()
    category = _node_category_name(node)
    return (
        path.startswith(("/mat/", "/shop/"))
        or category in _MATERIAL_NODE_CATEGORIES
        or "material" in type_name
        or "shader" in type_name
    )


def _looks_like_material_parm(parm):
    name = _safe_call(lambda: parm.name(), "") or ""
    label = _safe_call(lambda: parm.description(), "") or ""
    combined = f"{name} {label}".lower()
    return any(hint in combined for hint in _MATERIAL_PARAM_HINTS)


def _string_value(parm):
    value = _safe_call(lambda: parm.eval(), "")
    if isinstance(value, str):
        return value.strip()
    return ""


def _all_nodes(root, max_nodes):
    nodes = [root]
    children = _safe_call(lambda: root.allSubChildren(), ()) or ()
    for node in children:
        if len(nodes) >= max_nodes:
            break
        nodes.append(node)
    return nodes


def run(root_path="/", max_nodes=2000):
    """Inspect material nodes and references below root_path."""
    import hou  # type: ignore

    root = hou.node(root_path)
    if not root:
        return {"error": f"Root network does not exist: {root_path}"}

    max_nodes = max(1, min(int(max_nodes), 10000))
    nodes = _all_nodes(root, max_nodes)
    material_nodes = []
    references = []
    referenced_paths = set()

    for node in nodes:
        if _is_material_node(node):
            material_nodes.append({
                "path": node.path(),
                "name": node.name(),
                "type": _node_type_name(node),
                "category": _node_category_name(node),
            })

        for parm in _safe_call(lambda n=node: n.parms(), ()) or ():
            if not _looks_like_material_parm(parm):
                continue
            value = _string_value(parm)
            if not value or not value.startswith("/"):
                continue
            exists = hou.node(value) is not None
            referenced_paths.add(value)
            references.append({
                "node_path": node.path(),
                "parm": parm.name(),
                "value": value,
                "target_exists": exists,
            })

    material_paths = {node["path"] for node in material_nodes}
    return {
        "root_path": root_path,
        "scanned_node_count": len(nodes),
        "scan_truncated": len(nodes) >= max_nodes,
        "material_node_count": len(material_nodes),
        "material_nodes": material_nodes[:200],
        "material_nodes_truncated": len(material_nodes) > 200,
        "assignment_count": len(references),
        "assignments": references[:300],
        "assignments_truncated": len(references) > 300,
        "missing_references": [ref for ref in references if not ref["target_exists"]],
        "unused_material_nodes": sorted(material_paths - referenced_paths),
    }