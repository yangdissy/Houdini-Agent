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


def test_evaluate_only_returns_selected_check_scope():
    findings = houdini_hip_qc._evaluate(
        _scene(), project_fps=24, checks=["scene_settings"], include_manual=False
    )

    assert [finding["item"] for finding in findings] == [
        "A3 Houdini 版本",
        "A4 帧率与帧范围",
    ]


def test_scene_settings_reject_nonstandard_fps_without_project_standard():
    findings = houdini_hip_qc._evaluate(
        _scene(fps=30), checks=["scene_settings"], include_manual=False
    )

    fps_finding = _by_item(findings, "A4 帧率与帧范围")
    assert fps_finding["status"] == "fail"
    assert fps_finding["evidence"]["allowed_fps"] == [24, 25]


def test_collect_scene_skips_node_and_reference_scans_when_not_selected():
    class HipFile:
        @staticmethod
        def path():
            return "C:/show/seq010_shot020_sfx_v003.hip"

    class Playbar:
        @staticmethod
        def frameRange():
            return (1001, 1100)

    class Hou:
        hipFile = HipFile()
        playbar = Playbar()

        @staticmethod
        def applicationVersion():
            return (20, 5, 1)

        @staticmethod
        def fps():
            return 24

        @staticmethod
        def node(_path):
            raise AssertionError("file naming must not scan nodes")

        @staticmethod
        def fileReferences():
            raise AssertionError("file naming must not scan references")

    scene = houdini_hip_qc._collect_scene(Hou(), 10000, ["file_naming"])

    assert scene["nodes"] == []
    assert scene["references"] == []


def test_workflow_rules_flag_paths_versions_cache_type_and_direct_abc_cache():
    findings = houdini_hip_qc._evaluate(_scene(
        key_nodes=[
            {"path": "/obj/abc1", "name": "abc1", "type": "alembic", "parameters": {"fileName": "D:/show/model.abc"}, "inputs": []},
            {"path": "/obj/cache_v003", "name": "cache_v003", "type": "labs::filecache::2.0", "parameters": {"file": "$HIP/geo/cache.$F4.bgeo.sc"}, "inputs": ["/obj/abc1"]},
        ],
    ), checks=["workflow_rules"], include_manual=False)

    assert _by_item(findings, "W1 路径变量规范")["status"] == "fail"
    assert _by_item(findings, "W2 缓存与渲染节点不要自加版本号")["status"] == "fail"
    assert _by_item(findings, "W3 仅使用流程 File Cache")["status"] == "fail"
    direct_abc = _by_item(findings, "W4 ABC 不要直接 File Cache")
    assert direct_abc["status"] == "fail"
    assert direct_abc["evidence"]["connections"] == [
        {"filecache": "/obj/cache_v003", "alembic_input": "/obj/abc1"}
    ]


def test_workflow_rules_accept_job_paths_and_pipeline_cache():
    findings = houdini_hip_qc._evaluate(_scene(
        key_nodes=[
            {"path": "/obj/cache_smoke", "name": "cache_smoke", "type": "filecache", "parameters": {"file": "$JOB/geo/smoke.$F4.bgeo.sc"}, "inputs": []},
            {"path": "/obj/reference", "name": "reference", "type": "alembic", "parameters": {"fileName": "$OF_PROJ/assets/model.abc"}, "inputs": []},
        ],
    ), checks=["workflow_rules"], include_manual=False)

    assert all(finding["status"] == "pass" for finding in findings)


def test_workflow_rules_accept_hip_paths():
    findings = houdini_hip_qc._evaluate(_scene(
        key_nodes=[
            {"path": "/obj/cache_smoke", "name": "cache_smoke", "type": "filecache", "parameters": {"file": "$HIP/geo/smoke.$F4.bgeo.sc"}, "inputs": []},
        ],
    ), checks=["workflow_rules"], include_manual=False)

    path_finding = _by_item(findings, "W1 路径变量规范")
    assert path_finding["status"] == "pass"
    assert path_finding["evidence"]["hip_paths"][0]["value"] == "$HIP/geo/smoke.$F4.bgeo.sc"


def test_absolute_path_detection_matches_filepath_replace_rules():
    assert houdini_hip_qc._is_absolute_path("D:/show/model.abc") is True
    assert houdini_hip_qc._is_absolute_path("\\\\server\\show\\model.abc") is True
    assert houdini_hip_qc._is_absolute_path("$HIP/geo/model.bgeo.sc") is False
    assert houdini_hip_qc._is_absolute_path("$JOB/geo/model.bgeo.sc") is False
    assert houdini_hip_qc._uses_illegal_path_variable("$HFS/houdini/pic/default.rat") is True


def test_path_heuristic_ignores_code_and_detects_unregistered_file_values():
    class Parm:
        def __init__(self, name, value, description=""):
            self._name = name
            self._value = value
            self._description = description

        def name(self):
            return self._name

        def description(self):
            return self._description

        def rawValue(self):
            return self._value

    class NodeType:
        @staticmethod
        def nameWithCategory():
            return "Sop/custom_loader"

    class Node:
        def __init__(self):
            self._parms = [
                Parm("source", "D:/show/model.abc"),
                Parm("python_script", "D:/show/not_a_path.py"),
                Parm("scale", "100"),
            ]

        @staticmethod
        def type():
            return NodeType()

        def parms(self):
            return self._parms

    assert [parm.name() for parm in houdini_hip_qc._path_parameters(Node(), True)] == ["source"]


def test_base_type_name_strips_houdini_namespace():
    class NodeType:
        @staticmethod
        def nameWithCategory():
            return "Sop/labs::filecache::2.0"

    class Node:
        @staticmethod
        def type():
            return NodeType()

    assert houdini_hip_qc._base_type_name(Node()) == "Sop/filecache"


def test_workflow_rules_reject_hfs_asset_paths():
    findings = houdini_hip_qc._evaluate(_scene(
        key_nodes=[
            {"path": "/mat/shader", "name": "shader", "type": "materialbuilder", "parameters": {"texture": "$HFS/houdini/pic/default.rat"}, "inputs": []},
        ],
    ), checks=["workflow_rules"], include_manual=False)

    path_finding = _by_item(findings, "W1 路径变量规范")
    assert path_finding["status"] == "fail"
    assert path_finding["evidence"]["illegal_variable_paths"][0]["value"] == "$HFS/houdini/pic/default.rat"


def test_versioned_file_node_uses_configured_path_parameter():
    class Parm:
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

    file_parm = Parm("file")
    ignored_parm = Parm("other")

    class NodeType:
        @staticmethod
        def nameWithCategory():
            return "Sop/file::2.0"

    class Node:
        @staticmethod
        def type():
            return NodeType()

        @staticmethod
        def parms():
            return [file_parm, ignored_parm]

        @staticmethod
        def parm(name):
            return file_parm if name == "file" else None

    assert houdini_hip_qc._path_parameters(Node(), True) == [file_parm]