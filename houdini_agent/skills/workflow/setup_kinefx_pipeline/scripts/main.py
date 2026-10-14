"""KineFX rig/retarget blueprint Skill."""

from houdini_agent.skills.workflow._blueprint import build_blueprint, chain, node




def run(source_node_path, mode="rig"):
    source = str(source_node_path or "").strip()
    mode = str(mode or "rig").strip().lower()
    if not source or mode not in ("rig", "capture", "retarget"):
        return {"error": "source_node_path is required and mode must be rig, capture, or retarget."}
    type_chains = {
        "rig": [("skeleton", "skeleton", "build_skeleton"), ("pose", "rigpose", "rig_pose")],
        "capture": [("capture", "jointcapturebiharmonic", "capture_weights"), ("deform", "bonedeform", "deform_character")],
        "retarget": [("map", "mapoints", "map_skeleton"), ("retarget", "kinefx::retarget", "retarget_motion")],
    }
    boundaries = {
        "rig": ["skeleton", "animator controls and pose", "rig output"],
        "capture": ["capture geometry and skeleton inputs", "weights", "deformation output"],
        "retarget": ["source and target skeletons", "joint mapping", "retargeted motion output"],
    }
    entries = type_chains[mode]
    nodes = [node(node_id, node_type, name) for node_id, node_type, name in entries]
    nodes.append(node("output", "null", "OUT_KINEFX"))
    ids = [entry[0] for entry in entries] + ["output"]
    return build_blueprint(
        f"kinefx_{mode}", source.rsplit("/", 1)[0], nodes, chain(*ids),
        "Connect source_node_path to the first node. Retarget and capture workflows often require additional geometry/skeleton inputs; inspect connector labels before wiring.",
        source_node_path=source, mode=mode, final_node_id="output",
        module_boundaries=boundaries[mode],
        recommended_existing_skills=[
            "decompose_houdini_task",
            "design_houdini_parameter_ui",
            "handoff_houdini_network",
        ],
    )