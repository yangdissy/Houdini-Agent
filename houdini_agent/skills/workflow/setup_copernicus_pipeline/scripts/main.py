"""Copernicus texture pipeline blueprint Skill."""

from houdini_agent.skills.workflow._blueprint import build_blueprint, chain, node




def run(texture_name, resolution=2048, output_format="exr"):
    name = str(texture_name or "").strip()
    resolution = int(resolution)
    output_format = str(output_format or "exr").strip().lower()
    if not name or resolution < 64 or output_format not in ("exr", "png", "tif"):
        return {"error": "texture_name is required, resolution must be >= 64, and output_format must be exr, png, or tif."}
    path = f"$HIP/textures/{name}/{name}_packed.{output_format}"
    nodes = [
        node("pattern", "copnoise", "base_pattern", {"resolutionx": resolution, "resolutiony": resolution}),
        node("remap", "copramp", "shape_pattern"),
        node("pack", "copchanneljoin", "pack_channels"),
        node("output", "rop_comp", "WRITE_TEXTURE", {"copoutput": path}),
    ]
    return build_blueprint(
        "copernicus_texture", "/img", nodes, chain("pattern", "remap", "pack", "output"),
        "Copernicus node names vary substantially by Houdini version; use search_node_types and parameter schemas after dry run. Writing images needs explicit approval.",
        texture_name=name, resolution=resolution, output_path=path, final_node_id="output",
        module_boundaries=[
            {"role": "input_or_generation", "nodes": ["pattern"]},
            {"role": "processing", "nodes": ["remap"]},
            {"role": "channel_pack", "nodes": ["pack"]},
            {"role": "file_output", "nodes": ["output"]},
        ],
        recommended_existing_skills=[
            "decompose_houdini_task",
            "design_houdini_parameter_ui",
            "handoff_houdini_network",
        ],
    )