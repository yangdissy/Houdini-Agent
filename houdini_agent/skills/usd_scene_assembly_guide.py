# -*- coding: utf-8 -*-
"""LOPs/USD scene assembly workflow guide Skill.

Read-only guide skill: returns Solaris/LOP workflow advice. It does not import
hou and does not modify the scene.
"""

SKILL_INFO = {
    "name": "usd_scene_assembly_guide",
    "category": "workflow",
    "description": (
        "Return a read-only LOPs/USD scene assembly guide with stage planning, LOP node plan, "
        "USD-native material rules, viewport-first lookdev guidance, anti-patterns, and "
        "verification steps. Use before building Solaris scenes or lookdev setups."
    ),
    "risk_level": "low",
    "parameters": {
        "scene_description": {
            "type": "string",
            "description": "USD scene or lookdev setup the user wants to assemble.",
            "required": True,
        },
        "renderer": {
            "type": "string",
            "description": "karma, storm, or usd_preview. Default karma.",
            "required": False,
            "default": "karma",
        },
        "lookdev_first": {
            "type": "boolean",
            "description": "Whether to prioritize viewport/Hydra preview before final renders. Default true.",
            "required": False,
            "default": True,
        },
    },
}


def _normalize_renderer(renderer):
    value = (renderer or "karma").strip().lower()
    if value not in ("karma", "storm", "usd_preview"):
        return "karma"
    return value


def run(scene_description, renderer="karma", lookdev_first=True):
    """Return a USD-native, viewport-first LOP assembly guide."""
    if not scene_description or not str(scene_description).strip():
        return {"error": "scene_description is required."}

    renderer = _normalize_renderer(renderer)
    lookdev_first = bool(lookdev_first)

    return {
        "guide": "usd_scene_assembly",
        "category": "workflow",
        "risk_level": "low",
        "scene_description": str(scene_description).strip(),
        "renderer": renderer,
        "lookdev_first": lookdev_first,
        "recommended_workflow": [
            "Inspect the current /stage context, selected nodes, layer stack, and existing prim hierarchy before adding LOPs.",
            "Plan the USD stage layer by layer: asset references, SOP imports, layout, materials, lights, camera, render settings, and output.",
            "Use sublayer/reference/sopimport for scene inputs instead of Python-authored prim creation unless there is no native LOP path.",
            "Create materials inside materiallibrary LOPs and bind them with assignmaterial LOPs.",
            "Use viewport or Hydra preview for lookdev feedback before writing final renders to disk.",
            "Set the display flag on the intended final LOP and verify the visible composed stage.",
        ],
        "lop_node_plan": [
            "sublayer or reference for existing USD assets",
            "sopimport when SOP geometry must enter USD",
            "stage manager / add prim / edit properties only for deliberate USD structure edits",
            "materiallibrary for USD-native materials",
            "assignmaterial for material bindings",
            "dome light / environment light / area light for lookdev lighting",
            "camera for framed review",
            "karmarendersettings when renderer is karma",
            "usd rop or render product only after viewport validation",
        ],
        "node_search_keywords": [
            "sublayer", "reference", "sop import", "material library", "assign material",
            "dome light", "area light", "camera", "karma render settings", "usd rop",
        ],
        "material_rules": [
            "Do not build new Solaris lookdev materials in /mat when the target is a USD stage.",
            "Use materiallibrary LOP as the material container for USD-native shaders.",
            "Use assignmaterial LOP for bindings and verify prim paths match the composed stage.",
            "Keep material paths stable and readable so bindings remain inspectable.",
        ],
        "lookdev_rules": [
            "Start with viewport/Hydra preview and simple lighting before final render settings.",
            "Use low sample counts or preview renderer settings until composition, binding, and framing are verified.",
            "Only move to disk render after the display LOP, material bindings, lights, and camera are confirmed.",
        ],
        "anti_patterns": [
            "Do not use Python LOPs to create ordinary prims before checking native LOP nodes.",
            "Do not bind materials through ad hoc Python when assignmaterial can express the binding.",
            "Do not hand-edit USD layers for routine scene assembly if sublayer/reference/edit LOPs can keep the graph inspectable.",
            "Do not spend final-render time to answer basic lookdev or binding questions that viewport preview can answer.",
            "Do not claim materials are correct without checking prim paths and bindings on the composed stage.",
        ],
        "recommended_existing_skills": [
            "inspect_scene_context",
            "inspect_usd_stage",
            "get_node_card",
            "search_houdini_help",
            "validate_network_contract",
        ],
        "verification": [
            "Confirm the intended final LOP has the display flag.",
            "Inspect stage composition, layer stack, prim hierarchy, and payload/reference status.",
            "Check material binding paths and confirm bound materials exist under the materiallibrary output.",
            "Verify viewport preview with the chosen renderer or Hydra delegate before final render.",
            "Check camera, lights, render settings, and output paths only after stage composition is correct.",
        ],
    }