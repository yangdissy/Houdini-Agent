# -*- coding: utf-8 -*-
"""按参数搜索节点 Skill

在网络中递归搜索具有特定参数（可选匹配特定值）的节点，类似 grep。
纯只读遍历。
"""

SKILL_INFO = {
    "name": "find_nodes_by_param",
    "category": "graph",
    "description": (
        "在网络中搜索具有特定参数值的节点，类似 grep 搜索。"
        "适用于定位使用了某参数（或某参数值）的节点。"
    ),
    "risk_level": "low",
    "parameters": {
        "param_name": {
            "type": "string",
            "description": "参数名",
            "required": True,
        },
        "value": {
            "type": ["string", "number"],
            "description": "要匹配的值（可选，留空则列出所有有此参数的节点）",
            "required": False,
        },
        "network_path": {
            "type": "string",
            "description": "搜索的网络路径，留空使用 /obj",
            "required": False,
        },
        "recursive": {
            "type": "boolean",
            "description": "是否递归搜索子网络，默认 true",
            "required": False,
        },
    },
}


def run(param_name, value=None, network_path=None, recursive=True):
    """入口函数

    Args:
        param_name: 参数名
        value: 要匹配的参数值（可选）
        network_path: 网络路径（可选，默认 /obj）
        recursive: 是否递归

    Returns:
        dict: {network, param_name, value, match_count, matches, truncated}
    """
    import hou  # type: ignore

    network = hou.node(network_path) if network_path else hou.node("/obj")
    if not network:
        return {"error": f"网络不存在: {network_path or '/obj'}"}

    matches = []

    def search_in(parent):
        for node in parent.children():
            parm = node.parm(param_name)
            if parm:
                parm_value = parm.eval()
                if value is None or str(parm_value) == str(value):
                    matches.append({
                        "path": node.path(),
                        "type": node.type().name(),
                        "value": parm_value,
                    })
            if recursive and hasattr(node, "children"):
                search_in(node)

    search_in(network)

    truncated = len(matches) > 50
    return {
        "network": network.path(),
        "param_name": param_name,
        "value": value,
        "match_count": len(matches),
        "matches": matches[:50],
        "truncated": truncated,
    }
