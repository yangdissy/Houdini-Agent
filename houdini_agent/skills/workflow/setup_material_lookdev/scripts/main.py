"""MaterialX/Karma lookdev blueprint Skill."""

from houdini_agent.skills.workflow._blueprint import build_blueprint, chain, node




def run(material_name, mode="karma", source_node_path=""):
    material_name = str(material_name or "").strip()
    mode = str(mode or "karma").strip().lower()
    if not material_name:
        return {"error": "material_name is required."}
    if mode not in ("karma", "sop"):
        return {"error": "mode must be 'karma' or 'sop'."}
    if mode == "karma":
        nodes = [
            node("materiallibrary", "materiallibrary", "material_library"),
            node("assignmaterial", "assignmaterial", "assign_material", {"matspecpath1": f"/materials/{material_name}"}),
            node("light", "domelight", "lookdev_dome"),
            node("output", "null", "OUT_LOOKDEV"),
        ]
        connections = chain("materiallibrary", "assignmaterial", "light", "output")
        parent = "/stage"
    else:
        nodes = [
            node("material", "material", "assign_material", {"shop_materialpath1": f"/mat/{material_name}"}),
            node("output", "null", "OUT_LOOKDEV"),
        ]
        connections = chain("material", "output")
        parent = str(source_node_path or "").rsplit("/", 1)[0] or "/obj"
    return build_blueprint(
        f"{mode}_material_lookdev", parent, nodes, connections,
        "Create the actual shader graph separately after checking node types and parameters. Connect source geometry where applicable.",
        material_name=material_name, mode=mode, source_node_path=source_node_path, final_node_id="output",
        module_boundaries=(
            ["material definition", "material binding", "lookdev lighting", "review output"]
            if mode == "karma" else ["material assignment", "review output"]
        ),
        recommended_existing_skills=(
            ["decompose_houdini_task", "design_houdini_parameter_ui", "handoff_houdini_network"]
            if mode == "karma" else ["design_houdini_parameter_ui", "handoff_houdini_network"]
        ),
    )