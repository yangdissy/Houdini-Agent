# -*- coding: utf-8 -*-
"""One-click render setup blueprint Skill (MVP-2, render config).

Sibling of ``setup_pyro_sim`` / ``setup_dynamics_sim`` covering the render-config
part of the fxhoudinimcp Workflow category. Returns a NODE-BUILDING BLUEPRINT
(a structured dict) for a standard render ROP setup. This skill does NOT create
nodes and does NOT import ``hou`` — it only produces a recipe. The AI executes
the recipe using the existing harness-managed core tools (``create_nodes_batch``
+ ``connect_nodes`` + ``batch_set_parameters``), so every write stays inside the
audited / undo-wrapped / cook-protected path. This preserves the safety boundary
(blueprint approach 'a' from the MVP plan — no harness bypass).

Blueprint shape aligns 1:1 with ``create_nodes_batch``:
  - ``nodes``:       [{id, type, name, parameters}]
  - ``connections``: [{from, to, input}]  (ids reference nodes[].id)

Renderers:
  - karma:  Karma (USD/LOP) — builds a LOP render chain (camera + dome light +
            karmarendersettings + usdrender_rop).
  - mantra: Mantra (classic ROP) — builds an out/ ROP (ifd/mantra) node.
"""

SKILL_INFO = {
    "name": "setup_render",
    "category": "workflow",
    "description": (
        "Return a node-building BLUEPRINT for a standard render setup: Karma (USD/LOP) or "
        "Mantra (classic ROP). Does NOT modify the scene — it returns a recipe (nodes + "
        "connections + parameters) that you then build by calling create_nodes_batch (pass the "
        "blueprint's 'nodes' and 'connections' directly). Use when the user asks to 'set up "
        "rendering', 'configure a render', 'make a Karma/Mantra render'. Karma builds a LOP "
        "chain (camera + dome light + render settings + usdrender); Mantra builds an out/ ROP. "
        "After building, capture_viewport still works for quick previews."
    ),
    "risk_level": "normal",
    "parameters": {
        "renderer": {
            "type": "string",
            "description": "'karma' or 'mantra'. Karma = modern USD/LOP path (recommended); "
                           "Mantra = classic out/ ROP. Default 'karma'.",
            "required": False,
            "default": "karma",
        },
        "resolution": {
            "type": "string",
            "description": "Output resolution as 'WIDTHxHEIGHT', e.g. '1920x1080'. Default '1920x1080'.",
            "required": False,
            "default": "1920x1080",
        },
        "output_path": {
            "type": "string",
            "description": "Output image path (e.g. '$HIP/render/$HIPNAME.$F4.exr'). Optional; "
                           "leave empty to use the ROP default.",
            "required": False,
            "default": "",
        },
    },
}


def _parse_resolution(resolution):
    """Return (width, height) ints from 'WIDTHxHEIGHT', or (None, None, error)."""
    try:
        w, h = str(resolution).lower().split("x")
        w, h = int(w.strip()), int(h.strip())
    except (ValueError, AttributeError):
        return None, None, f"resolution must be 'WIDTHxHEIGHT', got '{resolution}'."
    if w <= 0 or h <= 0:
        return None, None, "resolution width/height must be positive."
    return w, h, None


def _karma_blueprint(width, height, output_path):
    """Karma LOP chain: camera -> domelight -> karmarendersettings -> usdrender_rop.

    Built inside /stage (LOP network). Parameters use best-effort standard names;
    the AI should dry_run first since LOP param names vary by version.
    """
    rendersettings_params = {
        "resolutionx": width,
        "resolutiony": height,
    }
    usdrender_params = {}
    if output_path:
        usdrender_params["outputimage"] = output_path

    nodes = [
        {
            "id": "camera",
            "type": "camera",
            "name": "render_cam",
            "parameters": {},
        },
        {
            "id": "domelight",
            "type": "domelight",
            "name": "render_domelight",
            "parameters": {},
        },
        {
            "id": "rendersettings",
            "type": "karmarendersettings",
            "name": "karma_settings",
            "parameters": rendersettings_params,
        },
        {
            "id": "usdrender",
            "type": "usdrender_rop",
            "name": "karma_render",
            "parameters": usdrender_params,
        },
    ]
    connections = [
        {"from": "camera", "to": "domelight", "input": 0},
        {"from": "domelight", "to": "rendersettings", "input": 0},
        {"from": "rendersettings", "to": "usdrender", "input": 0},
    ]
    return nodes, connections, "/stage", "usdrender"


def _mantra_blueprint(width, height, output_path):
    """Mantra classic ROP: a single ifd (mantra) node inside /out."""
    params = {
        "override_camerares": 1,
        "res_overridex": width,
        "res_overridey": height,
    }
    if output_path:
        params["vm_picture"] = output_path

    nodes = [
        {
            "id": "mantra",
            "type": "ifd",
            "name": "mantra_render",
            "parameters": params,
        },
    ]
    connections = []
    return nodes, connections, "/out", "mantra"


def run(renderer="karma", resolution="1920x1080", output_path=""):
    """Produce a render setup blueprint. Read-only, returns a recipe dict."""
    renderer = (renderer or "karma").strip().lower()
    if renderer not in ("karma", "mantra"):
        return {"error": f"renderer must be 'karma' or 'mantra', got '{renderer}'."}

    width, height, err = _parse_resolution(resolution)
    if err:
        return {"error": err}

    output_path = (output_path or "").strip()

    if renderer == "karma":
        nodes, connections, parent_path, rop_id = _karma_blueprint(width, height, output_path)
        context_note = (
            "Karma is a LOP-based (USD) render. Build these nodes inside the /stage LOP network "
            "(parent_path='/stage'). If /stage is empty, the render will have no scene geometry — "
            "make sure your SOP/scene is imported into the stage (e.g. via a sopimport LOP) first."
        )
    else:
        nodes, connections, parent_path, rop_id = _mantra_blueprint(width, height, output_path)
        context_note = (
            "Mantra is a classic ROP render (out/ context). Build inside /out (parent_path='/out'). "
            "It renders the current /obj scene; no LOP stage needed."
        )

    return {
        "blueprint": f"{renderer}_render",
        "renderer": renderer,
        "resolution": f"{width}x{height}",
        "output_path": output_path or "(ROP default)",
        "parent_path": parent_path,
        "nodes": nodes,
        "connections": connections,
        "execution": {
            "tool": "create_nodes_batch",
            "notes": (
                f"1) {context_note} "
                f"2) Pass parent_path='{parent_path}' plus this blueprint's 'nodes' and "
                "'connections' directly to create_nodes_batch. "
                "3) Render node/param names vary by Houdini version — run create_nodes_batch with "
                "dry_run=True first; if a node type or parameter is rejected, use search_node_types "
                "and get_parameter_schema to find the correct names. "
                f"4) The '{rop_id}' node is the ROP to render from."
            ),
        },
    }
