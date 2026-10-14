# -*- coding: utf-8 -*-
"""按参数搜索节点 Skill

在网络中递归搜索具有特定参数（可选匹配特定值）的节点，类似 grep。
纯只读遍历。
"""



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
