# -*- coding: utf-8 -*-
"""Tests for the read-only Houdini HIP QC Skill."""

from pathlib import Path

from houdini_agent import skills


_DESCRIPTOR = skills._parse_skill_markdown(
    Path(__file__).resolve().parents[1]
    / "houdini_agent" / "skills" / "workflow" / "houdini_hip_qc" / "SKILL.md"
)
houdini_hip_qc = skills._load_descriptor_entrypoint(_DESCRIPTOR)


def _scene(**overrides):
    scene = {
        "hip_path": "C:/show/seq010_shot020_sfx_v003.hip",
        "application_version": [20, 5, 1],
        "fps": 24.0,
        "frame_range": [1001.0, 1100.0],
        "key_nodes": [],
        "references": [],
        "scan_truncated": False,
    }
    scene.update(overrides)
    return scene


def _by_item(findings, item):
    return next(finding for finding in findings if finding["item"] == item)


def test_evaluate_flags_default_name_bad_paths_and_missing_reference():
    findings = houdini_hip_qc._evaluate(_scene(
        key_nodes=[
            {"path": "/obj/fx/filecache1", "name": "filecache1", "type": "filecache::2.0", "parameters": {"file": "$HIP/tmp/cache.$F.bgeo"}},
            {"path": "/out/Export_Vdb", "name": "Export_Vdb", "type": "geometry", "parameters": {"sopoutput": "$HIP/vdb/smoke.$F4.vdb"}},
        ],
        references=[{"reference": "$HIP/tex/missing.exr", "exists": False}],
    ), project_fps=24)

    assert _by_item(findings, "C2 集成节点必须改名")["status"] == "fail"
    cache_finding = _by_item(findings, "C4 缓存路径与扩展名")
    assert cache_finding["status"] == "fail"
    assert cache_finding["confidence"] == "high"
    assert cache_finding["evidence"]["nodes"][0]["path"] == "/obj/fx/filecache1"
    assert cache_finding["evidence"]["nodes"][0]["parameters"]["file"] == "$HIP/tmp/cache.$F.bgeo"
    assert _by_item(findings, "E3 VDB 发布路径")["status"] == "fail"
    reference_finding = _by_item(findings, "F3 外部引用")
    assert reference_finding["status"] == "fail"
    assert reference_finding["evidence"]["missing_references"] == ["$HIP/tex/missing.exr"]


def test_evaluate_accepts_compliant_detectable_values_and_marks_manual_checks_uncertain():
    findings = houdini_hip_qc._evaluate(_scene(
        key_nodes=[
            {"path": "/obj/fx/fire_cache", "name": "fire_cache", "type": "filecache::2.0", "parameters": {"file": "$HIP/geo/fire/v003/fire.$F4.bgeo.sc"}},
            {"path": "/out/Export_Vdb", "name": "Export_Vdb", "type": "export_vdb", "parameters": {"vdb_path": "$PUBLISHTOMAYA_PATH/vdb/fire/v003/fire.$F4.vdb"}},
        ],
    ), project_fps=24)

    assert _by_item(findings, "A3 Houdini 版本")["status"] == "pass"
    assert _by_item(findings, "A4 帧率与帧范围")["status"] == "pass"
    assert _by_item(findings, "C4 缓存路径与扩展名")["status"] == "pass"
    assert _by_item(findings, "E3 VDB 发布路径")["status"] == "pass"
    manual_finding = _by_item(findings, "A1 ChooseTask 上下文")
    assert manual_finding["status"] == "uncertain"
    assert manual_finding["confidence"] == "low"
    assert manual_finding["evidence"] == {"source": "manual_confirmation_required"}