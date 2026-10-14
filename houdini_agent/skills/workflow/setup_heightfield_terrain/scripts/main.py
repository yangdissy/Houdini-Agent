"""Heightfield terrain blueprint Skill."""

from houdini_agent.skills.workflow._blueprint import build_blueprint, chain, node




def run(terrain_name, size=1000, resolution=1024, erosion=True):
    name = str(terrain_name or "").strip()
    size, resolution = float(size), int(resolution)
    if not name or size <= 0 or resolution < 64:
        return {"error": "terrain_name is required; size must be positive and resolution >= 64."}
    nodes = [
        node("heightfield", "heightfield", "terrain_base", {"sizex": size, "sizey": size, "divsize": size / resolution}),
        node("noise", "heightfield_noise", "terrain_noise"),
    ]
    ids = ["heightfield", "noise"]
    if bool(erosion):
        nodes.append(node("erosion", "heightfield_erode", "terrain_erosion"))
        ids.append("erosion")
    nodes.extend([
        node("mask", "heightfield_maskbyfeature", "terrain_masks"),
        node("scatter", "heightfield_scatter", "terrain_scatter_points"),
        node("output", "null", f"OUT_{name.upper()}"),
    ])
    ids.extend(["mask", "scatter", "output"])
    return build_blueprint(
        "heightfield_terrain", "/obj", nodes, chain(*ids),
        "Create inside a geometry/SOP network rather than directly under /obj if the dry run rejects SOP nodes. Review erosion cost before cooking.",
        terrain_name=name, size=size, resolution=resolution, final_node_id="output",
    )