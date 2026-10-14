"""Geometry/export delivery blueprint Skill."""

from houdini_agent.skills.workflow._blueprint import build_blueprint, node




_FORMATS = {
    "abc": ("rop_alembic", "sopoutput", ".abc", "/out"),
    "usd": ("usd_rop", "lopoutput", ".usd", "/stage"),
    "fbx": ("rop_fbx", "sopoutput", ".fbx", "/out"),
    "bgeo": ("rop_geometry", "sopoutput", ".$F4.bgeo.sc", "/out"),
    "vdb": ("rop_geometry", "sopoutput", ".$F4.vdb", "/out"),
}


def run(source_node_path, format, asset_name, frame_start=1, frame_end=240):
    source = str(source_node_path or "").strip()
    export_format = str(format or "").strip().lower()
    asset = str(asset_name or "").strip()
    frame_start, frame_end = int(frame_start), int(frame_end)
    if not source or not asset or export_format not in _FORMATS:
        return {"error": "source_node_path and asset_name are required; format must be abc, usd, fbx, bgeo, or vdb."}
    if frame_end < frame_start:
        return {"error": "frame_end must be >= frame_start."}
    node_type, path_parm, extension, parent = _FORMATS[export_format]
    path = f"$HIP/export/{asset}/{asset}{extension}"
    nodes = [node("export", node_type, f"EXPORT_{asset}", {path_parm: path, "f1": frame_start, "f2": frame_end})]
    return build_blueprint(
        f"{export_format}_export", parent, nodes, [],
        "Bind source_node_path using the export node's verified source parameter or input. File writing requires separate explicit approval.",
        source_node_path=source, format=export_format, export_path=path, frame_range=[frame_start, frame_end], final_node_id="export",
    )