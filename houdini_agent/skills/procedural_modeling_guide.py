# -*- coding: utf-8 -*-
"""SOP procedural modeling workflow guide Skill.

Read-only guide skill: returns workflow advice for building SOP node chains.
It does not import hou and does not modify the scene.
"""

SKILL_INFO = {
    "name": "procedural_modeling_guide",
    "category": "workflow",
    "description": (
        "Return a read-only SOP procedural modeling guide with recommended workflow, "
        "node-chain suggestions, node-search keywords, anti-patterns, verification steps, "
        "and fallbacks. Use before creating geometry assets so the build favors native SOP "
        "nodes over VEX or Python."
    ),
    "risk_level": "low",
    "parameters": {
        "description": {
            "type": "string",
            "description": "Geometry or asset the user wants to create.",
            "required": True,
        },
        "output_context": {
            "type": "string",
            "description": "Target network context. Default '/obj'.",
            "required": False,
            "default": "/obj",
        },
        "complexity": {
            "type": "string",
            "description": "simple, medium, or complex. Controls recommendation detail.",
            "required": False,
            "default": "medium",
        },
    },
}


_COMPLEXITY_STEPS = {
    "simple": [
        "Identify the base primitive or existing source geometry.",
        "Build one clear SOP chain from blockout to final OUT node.",
        "Verify display flag, errors, and geometry summary before claiming completion.",
    ],
    "medium": [
        "Inspect the target context and existing source geometry before creating nodes.",
        "Block out large forms with native SOP primitives and transforms.",
        "Add modeling, grouping, attribute, scatter, copy, boolean, bevel, or UV stages as separate named nodes.",
        "Expose important controls on a CTRL null when values must remain art-directable.",
        "Verify display flag, node errors, geometry counts, groups, attributes, and viewport result.",
    ],
    "complex": [
        "Split the asset into named SOP branches: base forms, masks/groups, detail generation, instancing, cleanup, UV, and output.",
        "Use low-resolution blockout and preview density before increasing copies, subdivisions, volumes, or remesh resolution.",
        "Prefer reusable node parameters and CTRL null spare parameters for art direction.",
        "Cache or checkpoint expensive stages before high-density scatter, boolean, volume, or simulation-adjacent work.",
        "Verify each branch locally before merging, then inspect final display flag, errors, geometry statistics, groups, attributes, and viewport result.",
    ],
}


def _normalize_complexity(complexity):
    value = (complexity or "medium").strip().lower()
    if value not in _COMPLEXITY_STEPS:
        return "medium"
    return value


def run(description, output_context="/obj", complexity="medium"):
    """Return a SOP node-first modeling workflow guide."""
    if not description or not str(description).strip():
        return {"error": "description is required."}

    complexity = _normalize_complexity(complexity)
    output_context = (output_context or "/obj").strip() or "/obj"

    return {
        "guide": "procedural_modeling",
        "category": "workflow",
        "risk_level": "low",
        "description": str(description).strip(),
        "output_context": output_context,
        "node_first_rule": (
            "Build SOP node chains first. Use wrangles only when native SOPs cannot express "
            "the operation clearly, and use Python only as a last-resort implementation path."
        ),
        "recommended_workflow": _COMPLEXITY_STEPS[complexity],
        "suggested_node_chain": [
            "primitive or input source",
            "transform / matchsize / merge",
            "group / blast / split for masks and parts",
            "polyextrude / bevel / boolean / subdivide or remesh for form work",
            "attribrandomize / attribute adjust / normal for controlled variation",
            "scatter / copytopoints / instancer-style SOPs for repeated detail",
            "uvflatten / uvlayout when texture coordinates are needed",
            "null named OUT_asset with display flag",
        ],
        "node_search_keywords": [
            "box", "sphere", "grid", "curve", "transform", "matchsize", "merge",
            "group", "blast", "polyextrude", "polybevel", "boolean", "subdivide",
            "remesh", "scatter", "copy to points", "attribute randomize", "normal",
            "uv flatten", "uv layout", "null",
        ],
        "anti_patterns": [
            "Do not use a wrangle to create simple primitives that Box, Sphere, Grid, Curve, or Line SOP can create.",
            "Do not use VEX point deletion when Group/Blast/Split expresses the selection clearly.",
            "Do not hand-code bevels, booleans, extrusions, copying, or UV layout before checking native SOPs.",
            "Do not hide important art-direction numbers inside wrangles when CTRL null parameters would make them inspectable.",
            "Do not claim the model is complete without checking node errors and the displayed geometry.",
        ],
        "recommended_existing_skills": [
            "get_node_card",
            "search_houdini_help",
            "inspect_scene_context",
            "validate_network_contract",
        ],
        "verification": [
            "Confirm the final OUT node has the display flag or is otherwise the visible output.",
            "Check newly created nodes for errors or warnings.",
            "Inspect geometry counts, primitive types, groups, attributes, normals, and UVs relevant to the asset.",
            "Review viewport result at blockout density before increasing scatter, subdivision, remesh, or volume resolution.",
            "If a wrangle was unavoidable, verify VEX compilation and inspect a small sample of affected attributes or geometry.",
        ],
        "fallbacks": [
            "If no native SOP is suitable, query docs or node cards before choosing a wrangle.",
            "If a wrangle is used, keep it narrow, parameterize important values, and validate on low-density geometry first.",
            "If Python appears necessary, stop and confirm that existing harness-managed tools cannot perform the operation.",
        ],
    }