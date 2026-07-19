# -*- coding: utf-8 -*-
"""Houdini scene debugging workflow guide Skill.

Read-only guide skill: returns a diagnostic route for scene, node, SOP, USD,
simulation, and performance issues. It does not import hou and does not modify
the scene.
"""

SKILL_INFO = {
    "name": "debug_scene_workflow",
    "category": "scene",
    "description": (
        "Return a read-only Houdini debugging route with recommended existing skills, "
        "common causes, stop conditions, and verification steps. Use when a scene, node, "
        "SOP network, USD stage, simulation, or performance problem is reported."
    ),
    "risk_level": "low",
    "parameters": {
        "problem_description": {
            "type": "string",
            "description": "Problem or failure the user reports.",
            "required": True,
        },
        "scope": {
            "type": "string",
            "description": "scene, node, sop, usd, simulation, or performance. Default scene.",
            "required": False,
            "default": "scene",
        },
    },
}


_SCOPE_ROUTES = {
    "scene": [
        "Inspect hip file, frame, selection, current network, and visible panes.",
        "List node errors and identify whether the failure is local or upstream.",
        "Check display/render flags and confirm the user is looking at the intended output.",
        "Narrow the issue to node, SOP geometry, USD stage, simulation, external file, or performance scope.",
    ],
    "node": [
        "Inspect the failing node type, parameters, inputs, flags, and errors.",
        "Check upstream dependencies before changing the failing node.",
        "Validate parameter names, menu tokens, expressions, file paths, groups, and attributes.",
    ],
    "sop": [
        "Follow the displayed SOP chain from source to output and find the first node where geometry diverges.",
        "Check point/primitive/detail counts, groups, attributes, normals, UVs, packed geometry, and missing inputs.",
        "If VEX is involved, verify compilation and watch for ch()/chi() paths silently returning zero.",
    ],
    "usd": [
        "Inspect the displayed LOP, layer stack, prim hierarchy, references, payloads, variants, and purposes.",
        "Check material prim paths, assignmaterial bindings, collection paths, and viewport renderer.",
        "Verify composition before editing materials, lights, cameras, or render settings.",
    ],
    "simulation": [
        "Validate source geometry, collision geometry, units, frame range, timescale, and initial low-resolution settings.",
        "Cook only a cheap frame range or low-res test before changing expensive solver settings.",
        "Check cache state, substeps, constraints, collisions, and emitted attributes or volumes.",
    ],
    "performance": [
        "Locate the slow or memory-heavy node before optimizing broad networks.",
        "Check cache opportunities, preview density, display flags, heavy file IO, high scatter counts, booleans, remesh, volumes, and simulations.",
        "Apply one optimization at a time and measure again.",
    ],
}


def _normalize_scope(scope):
    value = (scope or "scene").strip().lower()
    if value not in _SCOPE_ROUTES:
        return "scene"
    return value


def run(problem_description, scope="scene"):
    """Return a structured debugging route without touching the scene."""
    if not problem_description or not str(problem_description).strip():
        return {"error": "problem_description is required."}

    scope = _normalize_scope(scope)

    return {
        "guide": "debug_scene_workflow",
        "category": "scene",
        "risk_level": "low",
        "problem_description": str(problem_description).strip(),
        "scope": scope,
        "recommended_workflow": _SCOPE_ROUTES[scope],
        "diagnostic_route": _SCOPE_ROUTES[scope],
        "recommended_skills": [
            "inspect_scene_context",
            "explain_node_error",
            "trace_dependencies",
            "validate_network_contract",
            "analyze_cook_performance" if scope == "performance" else "get_node_card",
            "inspect_usd_stage" if scope == "usd" else "search_houdini_help",
        ],
        "common_causes": [
            "Missing or disconnected inputs.",
            "Wrong display/render flag or wrong network context.",
            "Invalid parameter token, expression, channel reference, or menu value.",
            "Missing file path, missing cache, or path that only exists on another machine.",
            "Group, attribute, prim path, or material path mismatch.",
            "VEX compile errors or ch()/chi() paths returning default zero values.",
            "USD material binding, layer composition, purpose, variant, payload, or renderer mismatch.",
            "Simulation source, collision, scale, frame range, cache, or substep mismatch.",
        ],
        "anti_patterns": [
            "Do not edit a failing node before checking whether the real error starts upstream.",
            "Do not repeatedly tweak parameters after two failed attempts without collecting new evidence.",
            "Do not cook heavy simulations, renders, or dense networks when a low-res or narrow-frame check can disprove the theory.",
            "Do not use Python execution to inspect or mutate scene state when existing read-only inspection or harness-managed tools can do it.",
            "Do not claim a fix is complete without re-checking the originally observed failure.",
        ],
        "stop_conditions": [
            "If two consecutive fixes do not change the observed failure, stop editing and collect new evidence.",
            "If the next step would cook a heavy simulation or render, switch to a low-res or narrow-frame check first.",
            "If the suspected fix requires Python execution, confirm that native nodes or harness-managed tools cannot solve it.",
            "If a parameter, node type, or USD path is uncertain, query schema, node cards, docs, or scene inspection before editing.",
        ],
        "verification": [
            "Re-check the originally failing node or stage after the fix.",
            "Inspect upstream errors and confirm no new downstream errors were introduced.",
            "Verify geometry summary, stage hierarchy, material bindings, dependency chain, or performance measurement matching the problem scope.",
            "Use viewport/display output or a cheap cook to confirm behavior before final render, cache, or high-resolution simulation.",
            "State the evidence used for completion, not just that a tool returned success.",
        ],
    }