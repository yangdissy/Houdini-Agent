# -*- coding: utf-8 -*-
"""Read-only workflow guidance for Houdini simulation families."""


_DOMAIN_TERMS = {
    "flip": ("flip", "liquid", "water", "whitewater", "fluid", "splash"),
    "vellum": ("vellum", "cloth", "softbody", "soft body", "grain", "fabric"),
    "rbd": ("rbd", "destruction", "fracture", "bullet", "debris", "shatter"),
    "mpm": ("mpm", "sand", "snow", "mud", "granular"),
    "pyro": ("pyro", "smoke", "fire", "explosion", "flame"),
}

_COMMON = {
    "recommended_workflow": [
        "Inspect scene scale, animation range, source geometry, and collider motion.",
        "Read the relevant SideFX workflow and troubleshooting pages before choosing node types or parameters.",
        "Build source, collision, solve, cache, and post-process as named stages with inspectable boundaries.",
        "Run inspect_frame_range_risk before any sampled cook; only a complete low-risk report may proceed.",
        "After one user confirmation, use cook_sample_frames for at most three explicit representative frames; Houdini may be unresponsive, so wait patiently.",
        "Increase resolution only after motion, collisions, constraints, and caching are correct.",
    ],
    "verification": [
        "Confirm source attributes, topology, velocity, scale, and frame-dependent changes before solving.",
        "Check collider representation and motion at frames where contact begins and ends.",
        "Inspect solver warnings, changing geometry counts or fields, and cache output over multiple frames.",
        "Compare the displayed final output with the solver output so a stale cache or downstream branch cannot hide changes.",
        "After two failed fixes for the same symptom, stop changing parameters and return to the relevant help page.",
    ],
    "fallbacks": [
        "Use search_houdini_help and get_node_card before substituting a guessed node type or parameter.",
        "Run create_nodes_batch with dry_run=True for node types not validated in the current Houdini session.",
        "Keep the draft resolution and frame range small until the failure is isolated.",
    ],
}

_DOMAIN_GUIDES = {
    "flip": {
        "cost_model": "Particle separation controls particle count; surfacing voxel scale adds a separate downstream cost.",
        "module_boundaries": ["source and emission", "colliders", "FLIP solve", "particle cache", "surface and whitewater", "final cache"],
        "help_scopes": ["fluid/tips", "fluid/narrowband", "fluid/surfacing", "fluid/whitewater", "fluid/flipviscosity"],
        "node_search_keywords": ["flip solver", "particle fluid surface", "fluid source", "collision source", "whitewater"],
        "failure_signatures": [
            "Volume-like sources leak or disappear when their surface, separation, or scale is inconsistent.",
            "Fast or thin colliders tunnel when collision resolution and solver substeps are insufficient.",
            "A good particle solve can still produce a poor mesh when surfacing is tuned too early.",
        ],
        "recommended_existing_skills": ["search_houdini_help", "get_node_card", "setup_dynamics_sim", "validate_network_contract", "setup_cache_pipeline"],
    },
    "vellum": {
        "cost_model": "Point and constraint counts dominate cost; substeps and constraint iterations multiply it.",
        "module_boundaries": ["geometry preparation", "constraints", "colliders", "Vellum solve", "post-process", "cache"],
        "help_scopes": ["vellum/vellumtips", "vellum/cloth", "vellum/softbody", "vellum/grains", "vellum/collisions"],
        "node_search_keywords": ["vellum configure", "vellum constraints", "vellum solver", "vellum post process", "vellum io"],
        "failure_signatures": [
            "Stretching usually indicates an inadequate constraint model or iterations, not only low stiffness.",
            "Explosive motion often starts with intersecting geometry, inconsistent scale, or abrupt collider motion.",
            "Constraint attributes must be inspected before solver parameters are tuned around bad setup data.",
        ],
        "recommended_existing_skills": ["search_houdini_help", "get_node_card", "setup_dynamics_sim", "analyze_geometry_attribs", "validate_network_contract", "setup_cache_pipeline"],
    },
    "rbd": {
        "cost_model": "Active piece count, collision geometry complexity, constraints, and substeps dominate Bullet cost.",
        "module_boundaries": ["fracture and packed pieces", "physical properties", "constraints", "colliders", "Bullet solve", "debris and cache"],
        "help_scopes": ["destruction/constraints", "destruction/fracturing", "destruction/sop_solver", "destruction/troubleshooting"],
        "node_search_keywords": ["rbd material fracture", "rbd configure", "rbd constraints", "rbd bullet solver", "rbd unpack"],
        "failure_signatures": [
            "Unpacked or malformed pieces make collision and transform behavior unreliable.",
            "Incorrect name attributes or constraint endpoints cause pieces and constraints to mismatch.",
            "Excessive collision detail costs more than it contributes to the visible fracture motion.",
        ],
        "recommended_existing_skills": ["search_houdini_help", "get_node_card", "setup_dynamics_sim", "analyze_connectivity", "validate_network_contract", "setup_cache_pipeline"],
    },
    "mpm": {
        "cost_model": "Particle spacing, material point count, grid resolution, and substeps dominate memory and solve time.",
        "module_boundaries": ["source material and sampling", "colliders", "MPM solve", "material diagnostics", "surface or volume reconstruction", "cache"],
        "help_scopes": ["mpm/overview", "mpm/materials", "mpm/collisions", "mpm/troubleshooting"],
        "node_search_keywords": ["mpm source", "mpm material", "mpm collider", "mpm solver", "mpm surface"],
        "failure_signatures": [
            "Material scale or sampling that disagrees with particle spacing produces unstable or unrepresentative behavior.",
            "Collider sampling and thickness must be validated before increasing solver substeps.",
            "Sand, snow, and mud need different material models; matching only visual density is insufficient.",
        ],
        "recommended_existing_skills": ["search_houdini_help", "get_node_card", "analyze_geometry_attribs", "validate_network_contract", "setup_cache_pipeline"],
    },
}


def _route(task, requested_domain):
    if requested_domain != "auto":
        return requested_domain, "The caller explicitly selected the solver family."

    lowered = task.lower()
    matches = [
        domain for domain, terms in _DOMAIN_TERMS.items()
        if any(term in lowered for term in terms)
    ]
    if len(matches) == 1:
        return matches[0], "The task contains an unambiguous solver-family term."
    if not matches:
        return None, "The task contains no unambiguous FLIP, Vellum, RBD, MPM, or Pyro term."
    return None, "The task contains terms from multiple solver families."


def run(task, domain="auto", complexity="medium"):
    """Return solver selection, staged workflow, documentation, and checks."""
    if not task or not str(task).strip():
        return {"error": "task is required."}

    task = str(task).strip()
    domain = (domain or "auto").strip().lower()
    complexity = (complexity or "medium").strip().lower()
    selected, reason = _route(task, domain)

    if selected is None:
        return {
            "guide": "simulation_workflow",
            "domain": "unresolved",
            "routing_reason": reason,
            "candidate_domains": ["flip", "vellum", "rbd", "mpm"],
            "next_action": "Choose domain explicitly after confirming the intended material and solver behavior.",
        }

    if selected == "pyro":
        return {
            "guide": "simulation_workflow",
            "domain": "pyro",
            "routing_reason": reason,
            "handoff_skill": "setup_pyro_sim",
            "recommended_existing_skills": ["search_houdini_help", "get_node_card", "setup_pyro_sim", "setup_cache_pipeline"],
        }

    guide = _DOMAIN_GUIDES[selected]
    result = {
        "guide": "simulation_workflow",
        "category": "workflow",
        "risk_level": "low",
        "task": task,
        "domain": selected,
        "complexity": complexity,
        "routing_reason": reason,
    }
    result.update(guide)
    result.update(_COMMON)
    if complexity == "simple":
        result["recommended_workflow"] = result["recommended_workflow"][:4]
    elif complexity == "complex":
        result["recommended_workflow"] = [
            "Decompose the effect into independently verifiable source, collision, solve, cache, and post-process modules."
        ] + result["recommended_workflow"]
        result["recommended_existing_skills"] = ["decompose_houdini_task"] + result["recommended_existing_skills"]
    return result
