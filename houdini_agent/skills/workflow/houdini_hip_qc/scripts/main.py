# -*- coding: utf-8 -*-
"""Read-only QC checks for the current Houdini HIP scene."""

import os
import re




_PATH_HINTS = (
    "file", "path", "output", "picture", "sopoutput", "cache", "filename",
    "vm_picture", "vdb",
)
_KEY_TYPE_HINTS = ("filecache", "alembic", "geometry", "mantra", "export", "rop_")
_DEFAULT_INTEGRATION_NAMES = {"filecache1", "mantra1", "rop_alembic1", "rop_geometry1"}


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


def _collect_scene(hou, max_nodes):
    root = hou.node("/")
    all_nodes = list(_safe_call(lambda: root.allSubChildren(), ()) or ()) if root else []
    truncated = len(all_nodes) > max_nodes
    nodes = []
    key_nodes = []
    for node in all_nodes[:max_nodes]:
        type_name = _safe_call(lambda n=node: n.type().name(), "") or ""
        name = _safe_call(lambda n=node: n.name(), "") or ""
        path = _safe_call(lambda n=node: n.path(), "") or ""
        nodes.append({"path": path, "name": name, "type": type_name})
        lowered = f"{type_name} {name}".lower()
        if not any(hint in lowered for hint in _KEY_TYPE_HINTS):
            continue
        parameters = {}
        for parm in _safe_call(lambda n=node: n.parms(), ()) or ():
            parm_name = _safe_call(lambda p=parm: p.name(), "") or ""
            if any(hint in parm_name.lower() for hint in _PATH_HINTS):
                value = _raw_value(parm)
                if value is not None:
                    parameters[parm_name] = value
        key_nodes.append({"path": path, "name": name, "type": type_name, "parameters": parameters})

    references = []
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


def _evaluate(scene, project_fps=None):
    findings = []
    version = scene.get("application_version") or []
    if len(version) >= 2 and tuple(version[:2]) >= (19, 5):
        findings.append(_finding("A", "A3 Houdini 版本", "pass", f"当前版本为 {'.'.join(map(str, version))}。", "无需处理。", {"application_version": version}))
    else:
        findings.append(_finding("A", "A3 Houdini 版本", "fail", "当前 Houdini 版本低于 19.5 或无法确认。", "使用项目要求的 Houdini 19.5 或之后版本打开。", {"application_version": version}))

    fps = scene.get("fps")
    if project_fps is None:
        findings.append(_finding("A", "A4 帧率与帧范围", "uncertain", f"当前 fps={fps}，帧范围={scene.get('frame_range')}，未提供项目标准。", "提供项目 fps 与 Cut 帧范围后复核。", {"actual_fps": fps, "frame_range": scene.get("frame_range"), "expected_fps": None}, "low"))
    elif fps is not None and abs(float(fps) - float(project_fps)) < 0.001:
        findings.append(_finding("A", "A4 帧率与帧范围", "pass", f"当前 fps 与项目要求一致：{fps}。", "仍需人工确认各 ROP 的有效帧范围。", {"actual_fps": fps, "expected_fps": project_fps, "frame_range": scene.get("frame_range")}, "medium"))
    else:
        findings.append(_finding("A", "A4 帧率与帧范围", "fail", f"当前 fps={fps}，项目要求={project_fps}。", "修正 fps 后重新缓存。", {"actual_fps": fps, "expected_fps": project_fps, "frame_range": scene.get("frame_range")}))

    key_nodes = scene.get("key_nodes", [])
    default_nodes = [node["path"] for node in key_nodes if node.get("name", "").lower() in _DEFAULT_INTEGRATION_NAMES]
    findings.append(_finding(
        "C", "C2 集成节点必须改名", "fail" if default_nodes else "pass",
        "仍使用默认名称：" + ", ".join(default_nodes) if default_nodes else "未发现四类集成节点使用默认名称。",
        "将节点改为有意义的元素名。" if default_nodes else "无需处理。",
        {"default_named_nodes": default_nodes},
    ))

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

    hip_name = os.path.splitext(os.path.basename(scene.get("hip_path", "")))[0]
    valid_name = bool(re.match(r"^.+_.+_.+_v\d+$", hip_name, re.I))
    findings.append(_finding(
        "F", "F1 文件命名", "pass" if valid_name else "fail",
        f"HIP 文件名：{hip_name or '(未保存)'}。",
        "无需处理。" if valid_name else "按 场次_镜头_任务_v版本号 命名并保存。",
        {"hip_path": scene.get("hip_path", ""), "filename": hip_name, "pattern": "场次_镜头_任务_v版本号"},
    ))

    missing = [item["reference"] for item in scene.get("references", []) if not item.get("exists")]
    findings.append(_finding(
        "F", "F3 外部引用", "fail" if missing else "pass",
        "缺失引用：" + ", ".join(missing) if missing else "未发现缺失的外部文件引用。",
        "修复为下游机器可访问的规范路径。" if missing else "无需处理。",
        {"missing_references": missing, "checked_reference_count": len(scene.get("references", []))},
    ))

    manual_items = (
        ("A", "A1 ChooseTask 上下文", "重新执行 ChooseTask 并确认 tankconfig。"),
        ("A", "A2 项目目录结构", "人工核对 abc/audio/comp/desk/flip/geo/hda/render/scripts/sim/tex/video。"),
        ("B", "B1-B6 节点布局", "人工检查 0.01 总控、导入分类、颜色、渲染壳和布局。"),
        ("C", "C1/C3/C5-C7 TD 集成流程", "与 TD 预设和提交记录人工比对。"),
        ("D", "D1-D3 Daily 拍屏", "检查 flipbook 路径、EXR 序列和 Daily MOV。"),
        ("E", "E1/E2/E4-E7 Publish 导出", "人工核对 ABC 接法、禁改参数、场类型与 Publish 操作。"),
        ("F", "F2/F4 工程收尾", "人工清理临时节点；未知项向 TS 确认。"),
    )
    for module, item, fix in manual_items:
        findings.append(_finding(module, item, "uncertain", "该项无法仅凭当前只读场景数据可靠判定。", fix, {"source": "manual_confirmation_required"}, "low"))
    if scene.get("scan_truncated"):
        findings.append(_finding("F", "扫描完整性", "uncertain", "节点数超过 max_nodes，扫描结果已截断。", "提高 max_nodes 后重新运行。", {"scan_truncated": True}, "high"))
    return findings


def run(project_fps=None, max_nodes=10000):
    """Inspect the current HIP without loading, cooking, saving, or modifying it."""
    import hou  # type: ignore

    max_nodes = max(1, min(int(max_nodes), 50000))
    scene = _collect_scene(hou, max_nodes)
    findings = _evaluate(scene, project_fps)
    summary = {
        "fail": sum(item["status"] == "fail" for item in findings),
        "uncertain": sum(item["status"] == "uncertain" for item in findings),
        "pass": sum(item["status"] == "pass" for item in findings),
    }
    return {
        "hip_path": scene["hip_path"],
        "read_only": True,
        "summary": summary,
        "priority_fixes": [item for item in findings if item["status"] == "fail"],
        "findings": findings,
        "scope": "仅检查流程和工程规范，不评价艺术效果，也不修改 HIP。",
    }