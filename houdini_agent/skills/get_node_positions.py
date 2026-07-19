# -*- coding: utf-8 -*-
"""节点位置 Skill

读取节点的位置信息（坐标、类型），用于检查布局效果或手动微调时查看当前状态。
纯只读。
"""

SKILL_INFO = {
    "name": "get_node_positions",
    "category": "graph",
    "description": (
        "获取节点的位置信息（坐标、类型），用于检查布局效果或在手动微调时查看当前状态。"
    ),
    "risk_level": "low",
    "parameters": {
        "network_path": {
            "type": "string",
            "description": "父网络路径（如 /obj/geo1）。留空时若提供 node_paths 则用之，否则报错。",
            "required": False,
        },
        "node_paths": {
            "type": "array",
            "description": "要查询的节点完整路径列表。留空则返回整个网络下所有子节点的位置。",
            "required": False,
        },
    },
}


def run(network_path=None, node_paths=None):
    """入口函数

    Args:
        network_path: 父网络路径（node_paths 为空时使用）
        node_paths: 特定节点路径列表

    Returns:
        dict: {count, positions} 或 {error}
    """
    import hou  # type: ignore

    nodes = []
    if node_paths:
        for p in node_paths:
            n = hou.node(p)
            if n:
                nodes.append(n)
        if not nodes:
            return {"error": "指定的节点路径均无效"}
    else:
        parent = hou.node(network_path) if network_path else None
        if parent is None:
            try:
                editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
                if editor:
                    parent = editor.pwd()
            except Exception:
                pass
        if parent is None:
            return {"error": "未找到目标网络（请提供 network_path 或 node_paths）"}
        nodes = list(parent.children())
        if not nodes:
            return {"error": f"{parent.path()} 下没有子节点"}

    positions = []
    for n in nodes:
        pos = n.position()
        positions.append({
            "name": n.name(),
            "path": n.path(),
            "x": round(pos[0], 3),
            "y": round(pos[1], 3),
            "type": n.type().name(),
        })

    return {"count": len(positions), "positions": positions}
