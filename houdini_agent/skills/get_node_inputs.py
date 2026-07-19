# -*- coding: utf-8 -*-
"""节点输入端口 Skill

查节点输入端口的含义（210 个常用节点已 JSON 缓存，其余从 hou 读取）。
纯只读。
"""

import os
import json

SKILL_INFO = {
    "name": "get_node_inputs",
    "category": "graph",
    "description": (
        "查节点输入端口含义（210 个常用节点已 JSON 缓存，毫秒级返回）。"
        "连接现有节点前确认 input_index 含义、只关心端口不关心参数时用。"
        "需要参数信息或 menu items 用 get_node_card；查冷门节点也可退回 get_node_card。"
    ),
    "risk_level": "low",
    "parameters": {
        "node_type": {
            "type": "string",
            "description": "节点类型名称，如 'copytopoints', 'boolean', 'scatter'",
            "required": True,
        },
        "category": {
            "type": "string",
            "description": "节点类别，默认 'sop'（可选 obj/dop/vop）",
            "required": False,
        },
    },
}

_COMMON_NODE_INPUTS = None


def _load_common_node_inputs():
    """从 mcp/node_inputs.json 懒加载常见节点输入信息"""
    global _COMMON_NODE_INPUTS
    if _COMMON_NODE_INPUTS is not None:
        return _COMMON_NODE_INPUTS
    _COMMON_NODE_INPUTS = {}
    # skills/ 与 utils/mcp/ 同级于 houdini_agent/ 包下
    skill_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(
        os.path.dirname(skill_dir), "utils", "mcp", "node_inputs.json"
    )
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            _COMMON_NODE_INPUTS = json.load(f)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return _COMMON_NODE_INPUTS


def run(node_type, category="sop"):
    """入口函数

    Args:
        node_type: 节点类型名称
        category: 节点类别，默认 sop

    Returns:
        dict: {node_type, category, info, source} 或 {error}
    """
    type_lower = node_type.lower()

    common_inputs = _load_common_node_inputs()
    if type_lower in common_inputs:
        return {
            "node_type": node_type,
            "category": category,
            "info": common_inputs[type_lower],
            "source": "cache",
        }

    import hou  # type: ignore

    try:
        categories = hou.nodeTypeCategories()
        cat_obj = categories.get(category.capitalize()) or categories.get(category.upper())
        if not cat_obj:
            return {"error": f"未找到类别: {category}"}

        node_type_obj = None
        for name, nt in cat_obj.nodeTypes().items():
            if name.lower() == type_lower or name.lower().endswith(f"::{type_lower}"):
                node_type_obj = nt
                break

        if not node_type_obj:
            return {"error": f"未找到节点类型: {node_type}"}

        max_inputs = node_type_obj.maxNumInputs()
        min_inputs = node_type_obj.minNumInputs()

        info_lines = [
            f"节点: {node_type} ({node_type_obj.description()})",
            f"输入端口数量: {min_inputs}-{max_inputs}",
            "",
            "输入端口详情:",
        ]

        for i in range(min(max_inputs, 6)):
            try:
                label = node_type_obj.inputLabel(i)
                required = i < min_inputs
                req_str = "必需" if required else "可选"
                info_lines.append(f"  [{i}] {label} ({req_str})")
            except Exception:
                info_lines.append(f"  [{i}] Input {i}")

        return {
            "node_type": node_type,
            "category": category,
            "info": "\n".join(info_lines),
            "source": "hou",
        }
    except Exception as e:
        return {"error": f"获取输入信息失败: {e}"}
