# -*- coding: utf-8 -*-
"""One-click Pyro simulation blueprint Skill (MVP-2).

Returns a NODE-BUILDING BLUEPRINT (a structured dict) for a standard SOP-based
Pyro (fire/smoke) setup. This skill does NOT create nodes and does NOT import
``hou`` — it only produces a recipe. The AI executes the recipe using the
existing harness-managed core tools (``create_nodes_batch`` + ``connect_nodes``
+ ``batch_set_parameters``), so all write operations stay inside the audited /
undo-wrapped / cook-protected path. This preserves the safety boundary
(blueprint approach 'a' from the MVP plan).

Blueprint shape aligns 1:1 with ``create_nodes_batch``:
  - ``nodes``:       [{id, type, name, parameters}]
  - ``connections``: [{from, to, input}]  (ids reference nodes[].id)
"""

SKILL_INFO = {
    "name": "setup_pyro_sim",
    "category": "workflow",
    "description": (
        "Return a node-building BLUEPRINT for a standard SOP-based Pyro (smoke/fire) "
        "simulation. Does NOT modify the scene — it returns a recipe (nodes + connections + "
        "parameters) that you then build by calling create_nodes_batch (pass the blueprint's "
        "'nodes' and 'connections' directly). Use when the user asks to 'set up pyro', "
        "'make smoke/fire sim', or similar one-click sim requests. After building, the source "
        "node's output should feed the first blueprint node."
    ),
    "risk_level": "normal",
    "parameters": {
        "source_node_path": {
            "type": "string",
            "description": "Path of the existing SOP node providing emission geometry "
                           "(e.g. '/obj/geo1/sphere1'). Its output feeds the pyro source.",
            "required": True,
        },
        "sim_type": {
            "type": "string",
            "description": "'smoke' or 'fire'. Fire enables temperature/flame emission. Default 'smoke'.",
            "required": False,
            "default": "smoke",
        },
        "division_size": {
            "type": "number",
            "description": "Voxel size for the sim volume. Smaller = higher res / slower. Default 0.1.",
            "required": False,
            "default": 0.1,
        },
    },
}


def run(source_node_path, sim_type="smoke", division_size=0.1):
    """Produce a Pyro setup blueprint. Read-only, returns a recipe dict."""
    if not source_node_path or not str(source_node_path).strip():
        return {"error": "source_node_path is required (path to the emission SOP node)."}

    sim_type = (sim_type or "smoke").strip().lower()
    if sim_type not in ("smoke", "fire"):
        return {"error": f"sim_type must be 'smoke' or 'fire', got '{sim_type}'."}

    try:
        div = float(division_size)
    except (TypeError, ValueError):
        return {"error": f"division_size must be a number, got '{division_size}'."}
    if div <= 0:
        return {"error": "division_size must be greater than 0."}

    # Standard SOP-based Pyro chain (Houdini 19+):
    #   source geo -> pyrosource -> volumerasterizeattributes -> pyrosolver -> output
    fire_emit = sim_type == "fire"

    pyrosource_params = {
        # Emit density from the source geometry.
        "mode": "surface" if not fire_emit else "surface",
    }

    rasterize_params = {
        # Attributes to rasterize into volumes. density always; temperature/flame for fire.
        "attributes": "density temperature" if fire_emit else "density",
        "size": div,
    }

    pyrosolver_params = {
        # Fire uses combustion; smoke does not.
        "enable_combustion": 1 if fire_emit else 0,
    }

    nodes = [
        {
            "id": "pyrosource",
            "type": "pyrosource",
            "name": "pyro_source",
            "parameters": pyrosource_params,
        },
        {
            "id": "rasterize",
            "type": "volumerasterizeattributes",
            "name": "pyro_rasterize",
            "parameters": rasterize_params,
        },
        {
            "id": "pyrosolver",
            "type": "pyrosolver",
            "name": "pyro_solver",
            "parameters": pyrosolver_params,
        },
        {
            "id": "output",
            "type": "output",
            "name": "OUT_pyro",
            "parameters": {},
        },
    ]

    connections = [
        {"from": "pyrosource", "to": "rasterize", "input": 0},
        {"from": "rasterize", "to": "pyrosolver", "input": 0},
        {"from": "pyrosolver", "to": "output", "input": 0},
    ]

    return {
        "blueprint": "pyro_sim",
        "sim_type": sim_type,
        "source_node_path": source_node_path,
        "nodes": nodes,
        "connections": connections,
        "execution": {
            "tool": "create_nodes_batch",
            "notes": (
                "1) Choose parent_path = the parent network of source_node_path "
                "(usually the containing geo/SOP network). "
                "2) Pass this blueprint's 'nodes' and 'connections' directly to create_nodes_batch. "
                "3) After creation, connect source_node_path -> pyrosource (input 0) via connect_nodes. "
                "4) Recommend dry_run=True first if any node type is unfamiliar. "
                "5) The 'output' node (OUT_pyro) is the final displayable result."
            ),
        },
    }
