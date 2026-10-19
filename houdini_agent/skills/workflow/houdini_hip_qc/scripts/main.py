# -*- coding: utf-8 -*-
"""Read-only QC checks for the current Houdini HIP scene."""

import os
import re




_PATH_HINTS = (
    "file", "path", "output", "picture", "sopoutput", "cache", "filename",
    "vm_picture", "vdb",
)
_PATH_EXT_PATTERN = re.compile(
    r"\.(bgeo|sc|abc|usd|usdc|usda|vdb|exr|png|jpg|jpeg|tif|tiff|hip|ifd|fbx|obj|ass|rat)\b",
    re.I,
)
_CODE_PARM_HINTS = (
    "snippet", "script", "code", "command", "python", "vex", "expression",
    "vexpression", "callback", "hscript",
)
_NON_FILE_PARM_NAMES = {"primpath"}
_ILLEGAL_PATH_VARIABLES = ("$hfs",)
_ALL_PATH_PARM_TYPES = {
    "Lop/sublayer", "Lop/reference", "Lop/environment", "Vop/image",
    "Vop/classicshader", "Vop/principledshader", "Vop/materialbuilder",
}
_PATH_PARMS_BY_TYPE = {
    "Sop/file": "file", "Sop/dopio": "file", "Sop/filemerge": "file,filelist#",
    "Sop/filecache": "file,basedir", "Sop/export_vdb": "file",
    "Sop/tableimport": "file", "Sop/alembic": "fileName",
    "Sop/rop_alembic": "filename", "Sop/rop_fbx": "sopoutput",
    "Sop/rop_geometry": "sopoutput", "Sop/of_assexport": "file",
    "Sop/agent": "fbxfile,cachedir", "Sop/fbx_archive_import": "sFBXFile",
    "Sop/fbxcharacterimport": "fbxfile,animfbxfile", "Sop/vellumio": "file",
    "Sop/uvquickshade": "texture", "Sop/attribfrommap": "texture_channel,filename",
    "Lop/of3d": "file", "Lop/sopcache": "basedir", "Lop/usdcache": "lopoutput",
    "Lop/filecache": "lopoutput", "Lop/usdrender_rop": "outputimage",
    "Lop/of_arnoldrender": "file", "Lop/domelight": "xn__inputstexturefile_r3ah",
    "Lop/arnold_rendersettings": "productName", "Lop/karmarenderproperties": "picture",
    "Object/alembicxform": "fileName", "Object/alembicarchive": "fileName",
    "Object/arnold_light": "ar_light_color_texture", "Object/hlight": "projmap,light_texture",
    "Driver/ifd": "vm_picture", "Driver/arnold": "ar_picture",
    "Driver/geometry": "sopoutput", "Object/envlight": "env_map",
    "Object/cam": "vm_background", "Vop/texture": "map",
}
_KEY_TYPE_HINTS = ("filecache", "alembic", "geometry", "mantra", "export", "rop_")
_DEFAULT_INTEGRATION_NAMES = {"filecache1", "mantra1", "rop_alembic1", "rop_geometry1"}
_CHECKS = (
    "scene_settings", "node_naming", "cache_paths", "file_naming",
    "external_references", "workflow_rules",
)


def _safe_call(func, default=None):
    try:
        return func()
    except Exception:
        return default


def _raw_value(parm):
    value = _safe_call(lambda: parm.rawValue(), None)
    if value is None:
        value = _safe_call(lambda: parm.unexpandedString(), None)
    return None if value is None else str(value)


def _base_type_name(node):
    full_name = _safe_call(lambda: node.type().nameWithCategory(), "") or ""
    if "::" not in full_name:
        return full_name
    category, type_name = full_name.split("/", 1) if "/" in full_name else ("", full_name)
    parts = type_name.split("::")
    base_name = parts[-2] if len(parts) > 1 and re.fullmatch(r"\d+(?:\.\d+)*", parts[-1]) else parts[-1]
    return f"{category}/{base_name}" if category else base_name


def _looks_like_path(value):
    if not value or "\n" in value or "\r" in value:
        return False
    lowered = value.lower()
    if lowered.startswith(("op:", "opdef:", "shop:", "time:")):
        return False
    return (
        _is_absolute_path(value)
        or value.startswith(("./", "../"))
        or any(variable in lowered for variable in ("$job", "$hip", "$work", "$of_proj", "$proj"))
        or _PATH_EXT_PATTERN.search(value) is not None
    )


def _path_parameters(node, scan_fallback):
    all_parms = list(_safe_call(lambda: node.parms(), ()) or ())
    base_type = _base_type_name(node)
    configured = _PATH_PARMS_BY_TYPE.get(base_type)
    selected = []
    if configured:
        for name in (item.strip() for item in configured.split(",")):
            if name.endswith("#"):
                pattern = re.compile(re.escape(name[:-1]) + r"\d+")
                selected.extend(parm for parm in all_parms if pattern.fullmatch(_safe_call(lambda p=parm: p.name(), "") or ""))
            else:
                parm = _safe_call(lambda item=name: node.parm(item), None)
                if parm is not None:
                    selected.append(parm)
        return selected
    if not scan_fallback:
        return [
            parm for parm in all_parms
            if any(hint in (_safe_call(lambda p=parm: p.name(), "") or "").lower() for hint in _PATH_HINTS)
        ]
    for parm in all_parms:
        parm_name = _safe_call(lambda p=parm: p.name(), "") or ""
        description = _safe_call(lambda p=parm: p.description(), "") or ""
        combined = f"{parm_name} {description}".lower()
        if parm_name.lower() in _NON_FILE_PARM_NAMES or any(hint in combined for hint in _CODE_PARM_HINTS):
            continue
        value = _raw_value(parm)
        if value is not None and _looks_like_path(value):
            selected.append(parm)
    return selected


def _normalize_checks(checks):
    if checks is None:
        return None
    if isinstance(checks, str):
        checks = [checks]
    selected = []
    for check in checks:
        check = str(check).strip().lower()
        if check == "all":
            return list(_CHECKS)
        if check not in _CHECKS:
            raise ValueError("未知检查范围：{}。可选值：{} 或 all".format(check, ", ".join(_CHECKS)))
        if check not in selected:
            selected.append(check)
    if not selected:
        raise ValueError("checks 至少包含一个检查范围。")
    return selected


def _collect_scene(hou, max_nodes, checks):
    needs_nodes = any(check in checks for check in ("node_naming", "cache_paths", "workflow_rules"))
    root = hou.node("/") if needs_nodes else None
    all_nodes = list(_safe_call(lambda: root.allSubChildren(), ()) or ()) if root else []
    truncated = needs_nodes and len(all_nodes) > max_nodes
    nodes = []
    key_nodes = []
    for node in all_nodes[:max_nodes]:
        type_name = _safe_call(lambda n=node: n.type().name(), "") or ""
        name = _safe_call(lambda n=node: n.name(), "") or ""
        path = _safe_call(lambda n=node: n.path(), "") or ""
        input_paths = []
        if "workflow_rules" in checks:
            input_paths = [
                _safe_call(lambda item=input_node: item.path(), "") or ""
                for input_node in (_safe_call(lambda n=node: n.inputs(), ()) or ())
                if input_node is not None
            ]
        nodes.append({"path": path, "name": name, "type": type_name, "inputs": input_paths})
        lowered = f"{type_name} {name}".lower()
        if "workflow_rules" not in checks and not any(hint in lowered for hint in _KEY_TYPE_HINTS):
            continue
        parameters = {}
        for parm in _path_parameters(node, "workflow_rules" in checks):
            parm_name = _safe_call(lambda p=parm: p.name(), "") or ""
            value = _raw_value(parm)
            if value is not None:
                parameters[parm_name] = value
        key_nodes.append({"path": path, "name": name, "type": type_name, "parameters": parameters, "inputs": input_paths})

    references = []
    if "external_references" in checks:
        for _, reference in _safe_call(lambda: list(hou.fileReferences()), ()) or ():
            if not isinstance(reference, str):
                continue
            expanded = _safe_call(lambda value=reference: hou.expandString(value), reference)
            references.append({
                "reference": reference,
                "expanded": expanded,
                "exists": os.path.exists(expanded) if expanded else False,
            })

    return {
        "hip_path": _safe_call(lambda: hou.hipFile.path(), "") or "",
        "application_version": list(_safe_call(lambda: hou.applicationVersion(), ()) or ()),
        "fps": _safe_call(lambda: float(hou.fps()), None),
        "frame_range": _safe_call(lambda: list(hou.playbar.frameRange()), None),
        "nodes": nodes,
        "key_nodes": key_nodes,
        "references": references,
        "scan_truncated": truncated,
    }


def _finding(module, item, status, problem, fix, evidence=None, confidence="high"):
    return {
        "module": module,
        "item": item,
        "status": status,
        "problem": problem,
        "fix": fix,
        "evidence": evidence or {},
        "confidence": confidence,
    }


def _path_values(node):
    return [str(value) for value in node.get("parameters", {}).values()]


def _is_absolute_path(value):
    normalized = value.strip().replace("\\", "/")
    if not normalized or "$" in normalized:
        return False
    return bool(re.match(r"^[A-Za-z]:/", normalized) or normalized.startswith("//") or normalized.startswith("/"))


def _uses_illegal_path_variable(value):
    lowered = value.lower()
    return any(variable in lowered for variable in _ILLEGAL_PATH_VARIABLES)


def _evaluate(scene, project_fps=None, checks=None, include_manual=True):
    checks = list(_CHECKS) if checks is None else _normalize_checks(checks)
    findings = []
    if "scene_settings" in checks:
        version = scene.get("application_version") or []
        if len(version) >= 2 and tuple(version[:2]) >= (19, 5):
            findings.append(_finding("A", "A3 Houdini 版本", "pass", f"当前版本为 {'.'.join(map(str, version))}。", "无需处理。", {"application_version": version}))
        else:
            findings.append(_finding("A", "A3 Houdini 版本", "fail", "当前 Houdini 版本低于 19.5 或无法确认。", "使用项目要求的 Houdini 19.5 或之后版本打开。", {"application_version": version}))

        fps = scene.get("fps")
        if project_fps is None:
            standard_fps = fps is not None and any(abs(float(fps) - value) < 0.001 for value in (24.0, 25.0))
            findings.append(_finding(
                "A", "A4 帧率与帧范围", "uncertain" if standard_fps else "fail",
                f"当前 fps={fps}，帧范围={scene.get('frame_range')}，未提供项目标准。" if standard_fps else f"当前 fps={fps}，不符合自查清单要求的 24/25fps。",
                "提供项目 fps 与 Cut 帧范围后复核。" if standard_fps else "设置为项目要求的 24 或 25fps，并提供 Cut 帧范围复核。",
                {"actual_fps": fps, "frame_range": scene.get("frame_range"), "expected_fps": None, "allowed_fps": [24, 25]},
                "low" if standard_fps else "high",
            ))
        elif fps is not None and abs(float(fps) - float(project_fps)) < 0.001:
            findings.append(_finding("A", "A4 帧率与帧范围", "pass", f"当前 fps 与项目要求一致：{fps}。", "仍需人工确认各 ROP 的有效帧范围。", {"actual_fps": fps, "expected_fps": project_fps, "frame_range": scene.get("frame_range")}, "medium"))
        else:
            findings.append(_finding("A", "A4 帧率与帧范围", "fail", f"当前 fps={fps}，项目要求={project_fps}。", "修正 fps 后重新缓存。", {"actual_fps": fps, "expected_fps": project_fps, "frame_range": scene.get("frame_range")}))

    key_nodes = scene.get("key_nodes", [])
    if "node_naming" in checks:
        default_nodes = [node["path"] for node in key_nodes if node.get("name", "").lower() in _DEFAULT_INTEGRATION_NAMES]
        findings.append(_finding(
            "C", "C2 集成节点必须改名", "fail" if default_nodes else "pass",
            "仍使用默认名称：" + ", ".join(default_nodes) if default_nodes else "未发现四类集成节点使用默认名称。",
            "将节点改为有意义的元素名。" if default_nodes else "无需处理。",
            {"default_named_nodes": default_nodes},
        ))

    if "cache_paths" in checks:
        file_caches = [node for node in key_nodes if "filecache" in f"{node.get('type', '')} {node.get('name', '')}".lower()]
        bad_cache_paths = []
        for node in file_caches:
            values = _path_values(node)
            if not any("$HIP/geo/" in value.replace("\\", "/") and re.search(r"\$F4\.bgeo\.sc(?:$|[^a-z])", value, re.I) for value in values):
                bad_cache_paths.append(node["path"])
        findings.append(_finding(
            "C", "C4 缓存路径与扩展名", "fail" if bad_cache_paths else ("pass" if file_caches else "uncertain"),
            "路径不符合 $HIP/geo/.../$F4.bgeo.sc：" + ", ".join(bad_cache_paths) if bad_cache_paths else ("File Cache 路径符合规范。" if file_caches else "未发现 File Cache 节点。"),
            "改回 TD 预设路径表达式。" if bad_cache_paths else ("无需处理。" if file_caches else "确认场景是否应包含缓存节点。"),
            {"nodes": [{"path": node["path"], "parameters": node.get("parameters", {})} for node in file_caches]},
            "high" if file_caches else "low",
        ))

        vdb_nodes = [node for node in key_nodes if "vdb" in f"{node.get('type', '')} {node.get('name', '')}".lower()]
        bad_vdb_paths = [node["path"] for node in vdb_nodes if not any("$PUBLISHTOMAYA_PATH" in value for value in _path_values(node))]
        findings.append(_finding(
            "E", "E3 VDB 发布路径", "fail" if bad_vdb_paths else ("pass" if vdb_nodes else "uncertain"),
            "未使用 $PUBLISHTOMAYA_PATH：" + ", ".join(bad_vdb_paths) if bad_vdb_paths else ("VDB 导出路径使用发布变量。" if vdb_nodes else "未发现 VDB 导出节点。"),
            "将 VDB Path 改为 $PUBLISHTOMAYA_PATH/vdb/...。" if bad_vdb_paths else ("无需处理。" if vdb_nodes else "确认场景是否需要 VDB 导出。"),
            {"nodes": [{"path": node["path"], "parameters": node.get("parameters", {})} for node in vdb_nodes]},
            "high" if vdb_nodes else "low",
        ))

    if "file_naming" in checks:
        hip_name = os.path.splitext(os.path.basename(scene.get("hip_path", "")))[0]
        valid_name = bool(re.match(r"^.+_.+_.+_v\d+$", hip_name, re.I))
        findings.append(_finding(
            "F", "F1 文件命名", "pass" if valid_name else "fail",
            f"HIP 文件名：{hip_name or '(未保存)'}。",
            "无需处理。" if valid_name else "按 场次_镜头_任务_v版本号 命名并保存。",
            {"hip_path": scene.get("hip_path", ""), "filename": hip_name, "pattern": "场次_镜头_任务_v版本号"},
        ))

    if "external_references" in checks:
        missing = [item["reference"] for item in scene.get("references", []) if not item.get("exists")]
        findings.append(_finding(
            "F", "F3 外部引用", "fail" if missing else "pass",
            "缺失引用：" + ", ".join(missing) if missing else "未发现缺失的外部文件引用。",
            "修复为下游机器可访问的规范路径。" if missing else "无需处理。",
            {"missing_references": missing, "checked_reference_count": len(scene.get("references", []))},
        ))

    if "workflow_rules" in checks:
        path_nodes = [node for node in key_nodes if node.get("parameters")]
        absolute_paths = []
        illegal_variable_paths = []
        hip_paths = []
        for node in path_nodes:
            for parm_name, value in node.get("parameters", {}).items():
                path_item = {"path": node["path"], "parameter": parm_name, "value": value}
                if _is_absolute_path(str(value)):
                    absolute_paths.append(path_item)
                if _uses_illegal_path_variable(str(value)):
                    illegal_variable_paths.append(path_item)
                if "$HIP" in str(value).upper():
                    hip_paths.append(path_item)
        findings.append(_finding(
            "W", "W1 路径变量规范", "fail" if absolute_paths or illegal_variable_paths else "pass",
            "发现绝对路径或非法路径变量。" if absolute_paths or illegal_variable_paths else "已扫描路径未发现绝对路径或非法路径变量。",
            "使用项目路径变量替换绝对路径；$HFS 不能作为资产路径。" if absolute_paths or illegal_variable_paths else "无需处理。",
            {"absolute_paths": absolute_paths, "illegal_variable_paths": illegal_variable_paths, "hip_paths": hip_paths},
            "high",
        ))

        versioned_names = [
            node["path"] for node in key_nodes
            if any(hint in f"{node.get('type', '')} {node.get('name', '')}".lower() for hint in ("filecache", "mantra", "render"))
            and re.search(r"(?:^|_)v\d+(?:_|$)", node.get("name", ""), re.I)
        ]
        findings.append(_finding(
            "W", "W2 缓存与渲染节点不要自加版本号", "fail" if versioned_names else "pass",
            "节点名包含额外 v* 版本号：" + ", ".join(versioned_names) if versioned_names else "未发现缓存或渲染节点名包含额外 v* 版本号。",
            "移除节点名中的版本号，使用流程预设版本控制。" if versioned_names else "无需处理。",
            {"versioned_nodes": versioned_names},
        ))

        unsupported_caches = [
            node["path"] for node in key_nodes
            if "filecache" in node.get("type", "").lower()
            and ("labs" in node.get("type", "").lower() or "::" in node.get("type", ""))
        ]
        findings.append(_finding(
            "W", "W3 仅使用流程 File Cache", "fail" if unsupported_caches else "pass",
            "发现流程不支持的 File Cache 类型：" + ", ".join(unsupported_caches) if unsupported_caches else "未发现 Labs 或带命名空间的 File Cache。",
            "替换为公司流程提供的 File Cache 节点。" if unsupported_caches else "无需处理。",
            {"unsupported_filecache_nodes": unsupported_caches},
        ))

        nodes_by_path = {node["path"]: node for node in key_nodes}
        abc_to_cache = []
        for node in key_nodes:
            if "filecache" not in node.get("type", "").lower():
                continue
            for input_path in node.get("inputs", []):
                input_node = nodes_by_path.get(input_path, {})
                if "alembic" in input_node.get("type", "").lower():
                    abc_to_cache.append({"filecache": node["path"], "alembic_input": input_path})
        findings.append(_finding(
            "W", "W4 ABC 不要直接 File Cache", "fail" if abc_to_cache else "pass",
            "发现 Alembic 节点直接连接 File Cache。" if abc_to_cache else "未发现 Alembic 节点直接连接 File Cache。",
            "在缓存前显式解包/转换 ABC 几何，避免 Windows 与 Ubuntu 间路径引用失效。" if abc_to_cache else "无需处理。",
            {"connections": abc_to_cache},
        ))

    manual_items = (
        ("A", "A1 ChooseTask 上下文", "重新执行 ChooseTask 并确认 tankconfig。"),
        ("A", "A2 项目目录结构", "人工核对 abc/audio/comp/desk/flip/geo/hda/render/scripts/sim/tex/video。"),
        ("B", "B1-B6 节点布局", "人工检查 0.01 总控、导入分类、颜色、渲染壳和布局。"),
        ("C", "C1/C3/C5-C7 TD 集成流程", "与 TD 预设和提交记录人工比对。"),
        ("D", "D1-D3 Daily 拍屏", "检查 flipbook 路径、EXR 序列和 Daily MOV。"),
        ("E", "E1/E2/E4-E7 Publish 导出", "人工核对 ABC 接法、禁改参数、场类型与 Publish 操作。"),
        ("F", "F2/F4 工程收尾", "人工清理临时节点；未知项向 TS 确认。"),
        ("W", "W5 农场任务模式", "人工确认含 Solver/帧依赖的 File Cache 使用 Simulation；渲染使用 Sequences。"),
        ("W", "W6 渲染层命名", "人工确认层名至少四个字母、不以数字开头且语义明确。"),
        ("W", "W7 SFX 提交清单", "人工确认最终资产、handle、尺寸、相机/缓存更新、UV、材质、单帧渲染和隐藏层。"),
        ("W", "W8 VDB 下游设置", "人工确认 Maya 中放大 100 倍、density channel 与 0.01 密度缩放。"),
        ("Q", "Q1 通用艺术自查", "对照客户参考和前后镜头，人工确认叙事目的、比例层次、视觉重心、动态节奏与工程整洁度。"),
        ("Q", "Q2 运动模糊与技术规格", "人工确认最终输出几何具有正确 velocity，渲染器 shutter 设置、分辨率、色彩空间、Cut 范围和交付格式正确。"),
        ("Q", "Q3 特效类别自查", "按镜头类型人工检查魔法/能量、破碎/爆炸、烟雾/云、水体或布料的形态、运动、碰撞、层次与消散。"),
        ("Q", "Q4 灯光材质自查", "人工确认受光与 Plate 一致、阴影和交互光正确，材质、透明排序、Ray Depth、Volume Lighting 与色彩空间正确。"),
        ("Q", "Q5 合成与最终审查", "逐帧检查闪烁、跳帧、噪点、边缘和 AOV；完成 AB 对比、Peer Review、Nuke 清理与交付说明。"),
    )
    if include_manual:
        for module, item, fix in manual_items:
            findings.append(_finding(module, item, "uncertain", "该项无法仅凭当前只读场景数据可靠判定。", fix, {"source": "manual_confirmation_required"}, "low"))
    if scene.get("scan_truncated") and any(check in checks for check in ("node_naming", "cache_paths", "workflow_rules")):
        findings.append(_finding("F", "扫描完整性", "uncertain", "节点数超过 max_nodes，扫描结果已截断。", "提高 max_nodes 后重新运行。", {"scan_truncated": True}, "high"))
    return findings


def run(checks=None, project_fps=None, max_nodes=10000):
    """Inspect the current HIP without loading, cooking, saving, or modifying it."""
    import hou  # type: ignore

    selected_checks = _normalize_checks(checks)
    if selected_checks is None:
        return {
            "status": "selection_required",
            "read_only": True,
            "available_checks": list(_CHECKS) + ["all"],
            "message": "请先确认要检查的范围，可多选，或选择 all。",
        }

    max_nodes = max(1, min(int(max_nodes), 50000))
    scene = _collect_scene(hou, max_nodes, selected_checks)
    include_manual = isinstance(checks, str) and checks.strip().lower() == "all"
    include_manual = include_manual or any(str(check).strip().lower() == "all" for check in checks)
    findings = _evaluate(scene, project_fps, selected_checks, include_manual=include_manual)
    summary = {
        "fail": sum(item["status"] == "fail" for item in findings),
        "uncertain": sum(item["status"] == "uncertain" for item in findings),
        "pass": sum(item["status"] == "pass" for item in findings),
    }
    return {
        "hip_path": scene["hip_path"],
        "read_only": True,
        "checks": selected_checks,
        "summary": summary,
        "priority_fixes": [item for item in findings if item["status"] == "fail"],
        "findings": findings,
        "scope": "仅检查流程和工程规范，不评价艺术效果，也不修改 HIP。",
    }