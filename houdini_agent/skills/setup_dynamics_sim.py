# -*- coding: utf-8 -*-
"""One-click dynamics simulation blueprint Skill (MVP-2, RBD/FLIP/Vellum).

Sibling of ``setup_pyro_sim`` covering the remaining fxhoudinimcp Workflow
sim types. Returns a NODE-BUILDING BLUEPRINT (a structured dict) for a standard
SOP-based dynamics setup. This skill does NOT create nodes and does NOT import
``hou`` — it only produces a recipe. The AI executes the recipe using the
existing harness-managed core tools (``create_nodes_batch`` + ``connect_nodes``
+ ``batch_set_parameters``), so every write stays inside the audited /
undo-wrapped / cook-protected path. This preserves the safety boundary
(blueprint approach 'a' from the MVP plan — no harness bypass).

Blueprint shape aligns 1:1 with ``create_nodes_batch``:
  - ``nodes``:       [{id, type, name, parameters}]
  - ``connections``: [{from, to, input}]  (ids reference nodes[].id)

Sim types (all use Houdini 19+ SOP-level solver SOPs, matching setup_pyro_sim):
  - rbd:    rigid body destruction / collision (rbdbulletsolver)
  - flip:   liquids (flipsolver via flipfluidobject-style SOP chain)
  - vellum: cloth / softbody / grains (vellumsolver)
"""

SKILL_INFO = {
    "name": "setup_dynamics_sim",
    "category": "workflow",
    "description": (
        "Return a node-building BLUEPRINT for a standard SOP-based dynamics simulation: "
        "RBD (rigid body), FLIP (liquid), or Vellum (cloth/softbody/grain). Does NOT modify "
        "the scene — it returns a recipe (nodes + connections + parameters) that you then build "
        "by calling create_nodes_batch (pass the blueprint's 'nodes' and 'connections' directly). "
        "Use when the user asks to 'set up RBD/destruction', 'make a FLIP/liquid sim', or "
        "'set up vellum cloth/softbody'. For smoke/fire use setup_pyro_sim instead. After building, "
        "the source node's output feeds the first blueprint node."
    ),
    "risk_level": "normal",
    "parameters": {
        "source_node_path": {
            "type": "string",
            "description": "Path of the existing SOP node providing the sim geometry "
                           "(e.g. '/obj/geo1/box1'). Its output feeds the sim source.",
            "required": True,
        },
        "sim_type": {
            "type": "string",
            "description": "'rbd', 'flip', or 'vellum'. Selects the solver chain. Required.",
            "required": True,
        },
        "vellum_mode": {
            "type": "string",
            "description": "Only for sim_type='vellum': 'cloth', 'softbody', or 'grain'. Default 'cloth'.",
            "required": False,
            "default": "cloth",
        },
    },
}


def _rbd_blueprint():
    """Rigid body destruction chain: source -> rbdconfigure -> rbdbulletsolver -> output."""
    nodes = [
        {
            "id": "rbdconfigure",
            "type": "rbdconfigure",
            "name": "rbd_configure",
            "parameters": {},
        },
        {
            "id": "rbdsolver",
            "type": "rbdbulletsolver",
            "name": "rbd_solver",
            # Ground collision on by default so pieces have something to hit.
            "parameters": {"groundtype": "1"},
        },
        {
            "id": "output",
            "type": "output",
            "name": "OUT_rbd",
            "parameters": {},
        },
    ]
    connections = [
        {"from": "rbdconfigure", "to": "rbdsolver", "input": 0},
        {"from": "rbdsolver", "to": "output", "input": 0},
    ]
    first_input_id = "rbdconfigure"
    return nodes, connections, first_input_id


def _flip_blueprint():
    """Liquid chain: source(as fluid) -> flipsolver -> particlefluidsurface -> output."""
    nodes = [
        {
            "id": "flipsolver",
            "type": "flipsolver",
            "name": "flip_solver",
            # Treat the source geometry as the initial fluid volume.
            "parameters": {"initialdata": "1"},
        },
        {
            "id": "surface",
            "type": "particlefluidsurface",
            "name": "flip_surface",
            "parameters": {},
        },
        {
            "id": "output",
            "type": "output",
            "name": "OUT_flip",
            "parameters": {},
        },
    ]
    connections = [
        {"from": "flipsolver", "to": "surface", "input": 0},
        {"from": "surface", "to": "output", "input": 0},
    ]
    first_input_id = "flipsolver"
    return nodes, connections, first_input_id


def _vellum_blueprint(vellum_mode):
    """Cloth/softbody/grain chain: source -> vellumconfigure -> vellumsolver -> output."""
    # vellumconfigure* SOP presets per mode.
    configure_type = {
        "cloth": "vellumconfigurecloth",
        "softbody": "vellumconfiguresoftbody",
        "grain": "vellumconfiguregrain",
    }.get(vellum_mode, "vellumconfigurecloth")

    nodes = [
        {
            "id": "vellumconfigure",
            "type": configure_type,
            "name": f"vellum_{vellum_mode}",
            "parameters": {},
        },
        {
            "id": "vellumsolver",
            "type": "vellumsolver",
            "name": "vellum_solver",
            "parameters": {},
        },
        {
            "id": "output",
            "type": "output",
            "name": "OUT_vellum",
            "parameters": {},
        },
    ]
    connections = [
        {"from": "vellumconfigure", "to": "vellumsolver", "input": 0},
        {"from": "vellumsolver", "to": "output", "input": 0},
    ]
    first_input_id = "vellumconfigure"
    return nodes, connections, first_input_id


def run(source_node_path, sim_type=None, vellum_mode="cloth"):
    """Produce a dynamics setup blueprint. Read-only, returns a recipe dict."""
    if not source_node_path or not str(source_node_path).strip():
        return {"error": "source_node_path is required (path to the sim source SOP node)."}

    sim_type = (sim_type or "").strip().lower()
    if sim_type not in ("rbd", "flip", "vellum"):
        return {"error": f"sim_type must be 'rbd', 'flip', or 'vellum', got '{sim_type}'. "
                         "For smoke/fire use setup_pyro_sim."}

    vellum_mode = (vellum_mode or "cloth").strip().lower()
    if sim_type == "vellum" and vellum_mode not in ("cloth", "softbody", "grain"):
        return {"error": f"vellum_mode must be 'cloth', 'softbody', or 'grain', got '{vellum_mode}'."}

    if sim_type == "rbd":
        nodes, connections, first_input_id = _rbd_blueprint()
    elif sim_type == "flip":
        nodes, connections, first_input_id = _flip_blueprint()
    else:
        nodes, connections, first_input_id = _vellum_blueprint(vellum_mode)

    result = {
        "blueprint": f"{sim_type}_sim",
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
                f"3) After creation, connect source_node_path -> {first_input_id} (input 0) via connect_nodes. "
                "4) Solver SOP types vary by Houdini version — run create_nodes_batch with dry_run=True "
                "first; if a node type is rejected, use search_node_types to find the correct name. "
                "5) The 'output' node is the final displayable result."
            ),
        },
    }
    if sim_type == "vellum":
        result["vellum_mode"] = vellum_mode
    return result
