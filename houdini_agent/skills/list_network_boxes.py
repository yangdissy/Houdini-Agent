# -*- coding: utf-8 -*-
"""列出 NetworkBox Skill

列出指定网络中所有 NetworkBox 及其包含的节点，用于了解网络分组组织情况。
纯只读。
"""

SKILL_INFO = {
    "name": "list_network_boxes",
    "category": "graph",
    "description": (
        "列出指定网络中所有 NetworkBox 及其包含的节点。用于了解当前网络的分组组织情况。"
    ),
    "risk_level": "low",
    "parameters": {
        "parent_path": {
            "type": "string",
            "description": "要查询的网络路径（如 /obj/geo1）。",
            "required": True,
        },
    },
}


def run(parent_path):
    """入口函数

    Args:
        parent_path: 父网络路径

    Returns:
        dict: {parent, box_count, boxes} 或 {error}
    """
    import hou  # type: ignore

    parent = hou.node(parent_path)
    if not parent:
        return {"error": f"父网络 '{parent_path}' 不存在"}

    boxes_info = []
    for box in parent.networkBoxes():
        nodes = box.nodes()
        boxes_info.append({
            "name": box.name(),
            "comment": box.comment() or "",
            "node_count": len(nodes),
            "nodes": [n.path() for n in nodes],
            "minimized": box.isMinimized(),
        })

    return {
        "parent": parent_path,
        "box_count": len(boxes_info),
        "boxes": boxes_info,
    }
