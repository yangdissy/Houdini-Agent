"""Instance scatter blueprint Skill."""

from houdini_agent.skills.workflow._blueprint import build_blueprint, chain, node




def run(surface_node_path, instance_node_path, mode="sop", count=1000):
    surface = str(surface_node_path or "").strip()
    instance = str(instance_node_path or "").strip()
    mode = str(mode or "sop").strip().lower()
    count = int(count)
    if not surface or not instance:
        return {"error": "surface_node_path and instance_node_path are required."}
    if mode not in ("sop", "usd") or count < 1:
        return {"error": "mode must be 'sop' or 'usd', and count must be positive."}
    if mode == "sop":
        nodes = [
            node("scatter", "scatter", "scatter_points", {"npts": count}),
            node("orient", "attribwrangle", "build_orientation"),
            node("copy", "copytopoints", "copy_instances", {"pack": 1}),
            node("output", "null", "OUT_INSTANCES"),
        ]
        connections = chain("scatter", "orient", "copy", "output")
        parent = surface.rsplit("/", 1)[0]
        notes = "Connect surface to scatter input 0 and instance geometry to copy input 1. Configure orient/pscale/variant attributes before copying."
    else:
        nodes = [
            node("sopimport", "sopimport", "scatter_points", {"soppath": surface}),
            node("instancer", "pointinstancer", "point_instancer"),
            node("output", "null", "OUT_INSTANCES"),
        ]
        connections = chain("sopimport", "instancer", "output")
        parent = "/stage"
        notes = "Bind instance_node_path as the Point Instancer prototype after checking the LOP parameter schema."
    return build_blueprint(
        f"{mode}_instance_scatter", parent, nodes, connections, notes,
        surface_node_path=surface, instance_node_path=instance, mode=mode, final_node_id="output",
    )