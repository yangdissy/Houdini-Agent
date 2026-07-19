# -*- coding: utf-8 -*-
"""节点类型说明卡 Skill

建节点前一站式查节点类型说明（无需先建节点）：min/max inputs、输入/输出端口 label、
is_generator、参数名+默认值+menu items（enum 合法值）。纯只读（Sop 探针会临时建/删节点）。
"""

SKILL_INFO = {
    "name": "get_node_card",
    "category": "graph",
    "description": (
        "建节点前一站式查节点类型说明（无需先建节点）：min/max inputs、输入/输出端口 label、"
        "is_generator、参数名+默认值+menu items（enum 合法值）。"
        "第一次用某节点类型、不确定接几个输入、不知道参数是 enum/float/string 时用。"
        "只想知道端口用 get_node_inputs skill；查已建好的节点参数用 get_parameter_schema。"
    ),
    "risk_level": "low",
    "parameters": {
        "node_type": {
            "type": "string",
            "description": "节点类型名，如 'scatter'、'copytopoints'、'rbdbulletsolver'。不带版本号时返回最新版。",
            "required": True,
        },
        "context": {
            "type": "string",
            "description": "节点类别，默认 'Sop'（可选 Lop/Dop/Cop/Chop/Top/Object/Driver/Vop）",
            "required": False,
        },
        "parm_filter": {
            "type": "string",
            "description": "可选：参数名/label 子串过滤，只返回匹配的参数",
            "required": False,
        },
        "max_parms": {
            "type": "integer",
            "description": "参数返回上限，默认 40",
            "required": False,
        },
    },
}


def run(node_type, context="Sop", parm_filter=None, max_parms=40):
    """入口函数

    Returns:
        dict: 节点类型说明卡，或 {error}
    """
    import hou  # type: ignore

    try:
        categories = hou.nodeTypeCategories()
    except Exception as exc:
        return {"error": f"读取 nodeTypeCategories 失败: {exc}"}

    # context 容错：sop/Sop/SOP 都接受
    category = None
    ctx_norm = (context or "Sop").strip()
    for key in (ctx_norm, ctx_norm.capitalize(), ctx_norm.upper(), ctx_norm.lower()):
        if key in categories:
            category = categories[key]
            break
    if category is None:
        return {"error": f"未知 context '{context}'。可用: {sorted(categories.keys())}"}

    try:
        node_types = category.nodeTypes()
    except Exception as exc:
        return {"error": f"读取节点类型失败: {exc}"}

    # 类型解析：精确 → 去版本号匹配 → did-you-mean
    resolved = None
    if node_type in node_types:
        resolved = node_types[node_type]
    else:
        for nt_name, nt_obj in node_types.items():
            if nt_name.split("::", 1)[0] == node_type:
                resolved = nt_obj
                break
    if resolved is None:
        from difflib import get_close_matches
        close = get_close_matches(node_type, list(node_types.keys()), n=5, cutoff=0.4)
        return {
            "error": f"节点类型 '{node_type}' 在 {category.name()} 中不存在"
                     + (f"。建议: {', '.join(close)}" if close else ""),
            "did_you_mean": close,
        }

    # 连接器 label：只对 Sop category 做探针（实例化临时节点读 inputLabels）
    input_labels = []
    output_labels = []
    try:
        cat_name = category.name()
        if cat_name == "Sop":
            temp_parent = None
            for child in hou.node("/obj").children():
                if child.childTypeCategory() == category:
                    temp_parent = child
                    break
            _probe_container_created = False
            if temp_parent is None:
                temp_parent = hou.node("/obj").createNode(
                    "geo", "__nodecard_probe__",
                    run_init_scripts=False, load_contents=False, exact_type_name=True)
                _probe_container_created = True
            if temp_parent is not None:
                probe = temp_parent.createNode(
                    resolved.name(), "__probe__",
                    run_init_scripts=False, load_contents=False, exact_type_name=True)
                try:
                    input_labels = [str(l) for l in probe.inputLabels()] if hasattr(probe, "inputLabels") else []
                except Exception:
                    pass
                try:
                    output_labels = [str(l) for l in probe.outputLabels()] if hasattr(probe, "outputLabels") else []
                except Exception:
                    pass
                try:
                    probe.destroy()
                except Exception:
                    pass
                if _probe_container_created:
                    try:
                        temp_parent.destroy()
                    except Exception:
                        pass
    except Exception:
        pass

    # 参数 schema（从 parmTemplateGroup 读，无需实例化）
    parms_out = []
    try:
        tpl_group = resolved.parmTemplateGroup()
        filter_lc = parm_filter.lower() if parm_filter else None
        for tpl in tpl_group.parmTemplates():
            try:
                name = tpl.name()
                label = tpl.label() if hasattr(tpl, "label") else name
                if filter_lc and filter_lc not in name.lower() and filter_lc not in label.lower():
                    continue
                if hasattr(tpl, "isHidden") and tpl.isHidden():
                    continue
                entry = {
                    "name": name,
                    "label": label,
                    "type": tpl.type().name() if hasattr(tpl, "type") else "Unknown",
                }
                try:
                    dv = tpl.defaultValue()
                    entry["default"] = list(dv) if isinstance(dv, tuple) else dv
                except Exception:
                    pass
                try:
                    items = tpl.menuItems() if hasattr(tpl, "menuItems") else None
                    if items:
                        entry["menu"] = list(items)[:15]
                except Exception:
                    pass
                parms_out.append(entry)
                if len(parms_out) >= max_parms:
                    break
            except Exception:
                continue
    except Exception as exc:
        return {"error": f"读取 parmTemplateGroup 失败: {exc}"}

    min_in = resolved.minNumInputs() if hasattr(resolved, "minNumInputs") else 0
    max_in = resolved.maxNumInputs() if hasattr(resolved, "maxNumInputs") else 0
    max_out = resolved.maxNumOutputs() if hasattr(resolved, "maxNumOutputs") else 0

    return {
        "type": resolved.name(),
        "label": resolved.description() if hasattr(resolved, "description") else resolved.name(),
        "context": category.name(),
        "min_inputs": min_in,
        "max_inputs": max_in,
        "max_outputs": max_out,
        "is_generator": min_in == 0,
        "input_labels": input_labels,
        "output_labels": output_labels,
        "parm_count": len(parms_out),
        "parms": parms_out,
    }
