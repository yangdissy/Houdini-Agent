# -*- coding: utf-8 -*-
"""Tests for the read-only Houdini HIP QC Skill."""

import sys
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


def test_all_scope_includes_network_analysis():
    assert "network_analysis" in houdini_hip_qc._normalize_checks(["all"])


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


def test_network_analysis_splits_large_boxes_and_unconnected_components():
    paths = ["/obj/fx/n{}".format(index) for index in range(12)]
    nodes = [
        {
            "path": path,
            "parent_path": "/obj/fx",
            "inputs": [paths[index - 1]] if index else [],
            "outputs": [paths[index + 1]] if index < 11 else [],
            "network_boxes": [{"name": "everything", "comment": "Misleading large box"}],
        }
        for index, path in enumerate(paths)
    ]

    groups = houdini_hip_qc._group_network_nodes(nodes)

    assert len(groups) > 1
    assert all(len(group["node_paths"]) <= 8 for group in groups)
    assert {path for group in groups for path in group["node_paths"]} == set(paths)
    assert all(group["requires_semantic_review"] for group in groups)


def test_network_analysis_contract_requires_per_group_analysis_and_full_coverage():
    nodes = [{
        "path": "/obj/fx/noise",
        "name": "noise",
        "type": "attribnoise",
        "parent_path": "/obj/fx",
        "inputs": [],
        "outputs": [],
        "key_parameters": {"amplitude": "2.5"},
        "comment": "",
        "bypassed": False,
        "network_boxes": [],
    }]
    groups = houdini_hip_qc._group_network_nodes(nodes)
    containers = [{"path": "/obj/fx", "type": "geo", "depth": 2, "child_count": 1}]

    contract = houdini_hip_qc._network_analysis_contract(nodes, groups, containers)

    assert contract["status"] == "analysis_required"
    assert contract["scene_mutations_allowed"] is False
    assert contract["coverage_audit"] == {
        "node_paths": ["/obj/fx/noise"],
        "node_count": 1,
        "group_count": 1,
        "container_paths": ["/obj/fx"],
        "require_exact_node_union": True,
        "require_all_containers_expanded_including_subnet_and_dop": True,
    }
    task = contract["group_tasks"][0]
    assert task["nodes"] == nodes
    assert task["required_output"]["node_roles"] == {}
    assert "group_purpose" in task["required_output"]
    assert "composition_reasons" in task["required_output"]


def test_network_analysis_finding_requires_analysis_without_duplicating_node_payload():
    nodes = [{
        "path": "/obj/fx/noise",
        "name": "noise",
        "type": "attribnoise",
        "parent_path": "/obj/fx",
        "inputs": [],
        "outputs": [],
        "comment": "",
        "bypassed": False,
        "network_boxes": [],
    }]
    groups = houdini_hip_qc._group_network_nodes(nodes)

    findings = houdini_hip_qc._evaluate(
        _scene(nodes=nodes, node_groups=groups),
        checks=["network_analysis"],
        include_manual=False,
    )

    finding = _by_item(findings, "N1 节点识别与逐组分析")
    assert finding["status"] == "uncertain"
    assert finding["evidence"] == {"group_count": 1, "container_count": 0}


def test_network_analysis_groups_long_and_cyclic_networks_without_recursion():
    paths = ["/obj/fx/n{:04d}".format(index) for index in range(1200)]
    nodes = [{
        "path": path,
        "parent_path": "/obj/fx",
        "inputs": [paths[(index - 1) % len(paths)]],
        "outputs": [paths[(index + 1) % len(paths)]],
        "network_boxes": [],
    } for index, path in enumerate(paths)]

    groups = houdini_hip_qc._group_network_nodes(nodes)

    assert all(len(group["node_paths"]) <= 8 for group in groups)
    assert {path for group in groups for path in group["node_paths"]} == set(paths)


def test_collect_network_analysis_includes_nested_container_nodes():
    class NodeType:
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

    class Node:
        def __init__(self, path, node_type, parent=None, children=None):
            self._path = path
            self._type = NodeType(node_type)
            self._parent = parent
            self._children = children or []

        def path(self): return self._path
        def name(self): return self._path.rsplit("/", 1)[-1]
        def type(self): return self._type
        def parent(self): return self._parent
        def children(self): return self._children
        def inputs(self): return []
        def outputs(self): return []
        def parms(self): return []
        def comment(self): return ""
        def isBypassed(self): return False
        def networkBoxes(self): return []

    dop_solver = Node("/obj/fx/dopnet1/solver1", "solver")
    dopnet = Node("/obj/fx/dopnet1", "dopnet", children=[dop_solver])
    geo = Node("/obj/fx", "geo", children=[dopnet])
    dopnet._parent = geo
    dop_solver._parent = dopnet

    class Root:
        @staticmethod
        def allSubChildren(): return [geo, dopnet, dop_solver]

    class HipFile:
        @staticmethod
        def path(): return "C:/show/test.hip"

    class Playbar:
        @staticmethod
        def frameRange(): return (1, 24)

    class Hou:
        hipFile = HipFile()
        playbar = Playbar()
        @staticmethod
        def node(_path): return Root()
        @staticmethod
        def applicationVersion(): return (20, 5, 1)
        @staticmethod
        def fps(): return 24

    scene = houdini_hip_qc._collect_scene(Hou(), 10000, ["network_analysis"])

    assert [node["path"] for node in scene["nodes"]] == [
        "/obj/fx", "/obj/fx/dopnet1", "/obj/fx/dopnet1/solver1"
    ]
    assert [node["depth"] for node in scene["nodes"]] == [2, 3, 4]
    assert [item["path"] for item in scene["network_containers"]] == [
        "/obj/fx", "/obj/fx/dopnet1"
    ]


def test_run_returns_group_tasks_container_tasks_and_nondefault_parameters(monkeypatch):
    class NodeType:
        def __init__(self, name): self._name = name
        def name(self): return self._name
        def nameWithCategory(self): return self._name

    class Parm:
        def __init__(self, name, value, is_default):
            self._name = name
            self._value = value
            self._is_default = is_default
        def name(self): return self._name
        def rawValue(self): return self._value
        def isAtDefault(self): return self._is_default

    class Node:
        def __init__(self, path, node_type, is_network=False, parms=None):
            self._path = path
            self._type = NodeType(node_type)
            self._is_network = is_network
            self._parms = parms or []
        def path(self): return self._path
        def name(self): return self._path.rsplit("/", 1)[-1]
        def type(self): return self._type
        def parent(self): return None
        def children(self): return []
        def isNetwork(self): return self._is_network
        def inputs(self): return []
        def outputs(self): return []
        def parms(self): return self._parms
        def comment(self): return ""
        def isBypassed(self): return False

    nodes = [
        Node("/obj/fx", "geo", is_network=True),
        Node("/obj/fx/noise", "attribnoise", parms=[
            Parm("amplitude", 2.5, False), Parm("frequency", 1, True)
        ]),
        Node("/obj/empty", "subnet", is_network=True),
    ]

    class Root:
        @staticmethod
        def allSubChildren(): return nodes

    class HipFile:
        @staticmethod
        def path(): return "C:/show/test.hip"

    class Playbar:
        @staticmethod
        def frameRange(): return (1, 24)

    class Hou:
        hipFile = HipFile()
        playbar = Playbar()
        @staticmethod
        def node(_path): return Root()
        @staticmethod
        def applicationVersion(): return (20, 5, 1)
        @staticmethod
        def fps(): return 24

    monkeypatch.setitem(sys.modules, "hou", Hou())
    result = houdini_hip_qc.run(checks=["network_analysis"])

    analysis = result["network_analysis"]
    assert result["status"] == "analysis_required"
    assert len(analysis["group_tasks"]) == 3
    noise_task = next(task for task in analysis["group_tasks"] if "/obj/fx/noise" in task["node_paths"])
    assert noise_task["nodes"][0]["key_parameters"] == {"amplitude": "2.5"}
    assert set(analysis["coverage_audit"]["container_paths"]) == {"/obj/fx", "/obj/empty"}
    assert {task["container_path"] for task in analysis["container_tasks"]} == {"/obj/fx", "/obj/empty"}


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