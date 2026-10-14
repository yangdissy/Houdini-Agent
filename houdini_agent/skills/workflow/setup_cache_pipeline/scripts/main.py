"""Cache pipeline blueprint Skill."""

from houdini_agent.skills.workflow._blueprint import build_blueprint, chain, node




def run(source_node_path, cache_name, version=1, frame_start=1, frame_end=240):
    source = str(source_node_path or "").strip()
    name = str(cache_name or "").strip()
    if not source or not name:
        return {"error": "source_node_path and cache_name are required."}
    if not name.replace("_", "").replace("-", "").isalnum():
        return {"error": "cache_name may contain only letters, digits, underscores, and hyphens."}
    version, frame_start, frame_end = int(version), int(frame_start), int(frame_end)
    if version < 1 or frame_end < frame_start:
        return {"error": "version must be positive and frame_end must be >= frame_start."}
    path = f"$HIP/cache/{name}/v{version:03d}/{name}.$F4.bgeo.sc"
    nodes = [
        node("cache", "filecache", f"CACHE_{name}", {"file": path, "f1": frame_start, "f2": frame_end}),
        node("output", "null", f"OUT_{name.upper()}"),
    ]
    return build_blueprint(
        "cache_pipeline", source.rsplit("/", 1)[0], nodes, chain("cache", "output"),
        "Connect source_node_path to cache input 0. Keep cache loading disabled until an explicitly approved write completes.",
        source_node_path=source, cache_path=path, frame_range=[frame_start, frame_end], final_node_id="output",
    )