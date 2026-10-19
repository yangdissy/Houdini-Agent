from unittest import mock

from tests.test_import_smoke import _install_thirdparty_stubs


_install_thirdparty_stubs()

from houdini_agent.utils.mcp import client as mcp_client
from houdini_agent.utils.mcp.client import HoudiniMCP


class _Category:
    def name(self):
        return "Sop"


class _NodeType:
    def __init__(self, name="null", category="Sop"):
        self._name = name
        self._category = category

    def name(self):
        return self._name

    def category(self):
        category = _Category()
        category.name = lambda: self._category
        return category


class _Node:
    def __init__(self, path="/obj/geo1/OUT", type_name="null", category="Sop", inputs=(), cook_error=None):
        self._path = path
        self._type = _NodeType(type_name, category)
        self._inputs = inputs
        self._cook_error = cook_error
        self.cook_calls = []
        self.geometry_calls = 0

    def path(self):
        return self._path

    def type(self):
        return self._type

    def inputs(self):
        return self._inputs

    def cook(self, force=False):
        self.cook_calls.append(force)
        if self._cook_error is not None:
            raise RuntimeError(self._cook_error)

    def geometry(self):
        self.geometry_calls += 1
        raise AssertionError("risk inspection must not evaluate geometry")


class _HouStub:
    def __init__(self, *nodes, frame=17.5):
        self._nodes = {node.path(): node for node in nodes}
        self._frame = frame
        self.set_frame_calls = []

    def node(self, path):
        return self._nodes.get(path)

    def frame(self):
        return self._frame

    def setFrame(self, frame):
        self._frame = frame
        self.set_frame_calls.append(frame)


def test_inspect_frame_range_risk_is_read_only_for_plain_sop():
    node = _Node()
    hou = _HouStub(node)
    client = object.__new__(HoudiniMCP)

    with mock.patch.object(mcp_client, "hou", hou):
        ok, report = client.inspect_frame_range_risk(
            "/obj/geo1/OUT", [1.0, 5.0, 10.0]
        )

    assert ok is True
    assert report["risk_level"] == "low"
    assert report["scan_complete"] is True
    assert report["frames"] == [1.0, 5.0, 10.0]
    assert node.cook_calls == []
    assert node.geometry_calls == 0
    assert hou.set_frame_calls == []


def test_cook_sample_frames_refuses_solver_upstream_without_cooking():
    solver = _Node("/obj/geo1/solver1", "solver", "Sop")
    output = _Node(inputs=(solver,))
    hou = _HouStub(output, solver)
    client = object.__new__(HoudiniMCP)

    with mock.patch.object(mcp_client, "hou", hou):
        ok, report = client.cook_sample_frames(output.path(), [1.0, 2.0])

    assert ok is False
    assert report["preflight"]["risk_level"] == "high"
    assert report["status"] == "blocked"
    assert output.cook_calls == []
    assert solver.cook_calls == []
    assert hou.set_frame_calls == []


def test_cook_sample_frames_runs_in_order_and_restores_original_frame():
    output = _Node()
    hou = _HouStub(output, frame=17.5)
    client = object.__new__(HoudiniMCP)

    with mock.patch.object(mcp_client, "hou", hou):
        ok, report = client.cook_sample_frames(output.path(), [1.0, 3.5, 2.0])

    assert ok is True
    assert report["status"] == "completed"
    assert [item["frame"] for item in report["frames"]] == [1.0, 3.5, 2.0]
    assert output.cook_calls == [False, False, False]
    assert hou.set_frame_calls == [1.0, 3.5, 2.0, 17.5]
    assert report["restore_succeeded"] is True


def test_cook_sample_frames_rejects_invalid_frames_before_changing_time():
    output = _Node()
    hou = _HouStub(output)
    client = object.__new__(HoudiniMCP)

    with mock.patch.object(mcp_client, "hou", hou):
        ok, report = client.cook_sample_frames(output.path(), [1.0, float("nan")])

    assert ok is False
    assert "有限数字" in report["preflight"]["error"]
    assert hou.set_frame_calls == []
    assert output.cook_calls == []


def test_cook_sample_frames_restores_frame_after_cook_error():
    output = _Node(cook_error="cook failed")
    hou = _HouStub(output, frame=23.25)
    client = object.__new__(HoudiniMCP)

    with mock.patch.object(mcp_client, "hou", hou):
        ok, report = client.cook_sample_frames(output.path(), [2.0])

    assert ok is False
    assert report["status"] == "failed"
    assert report["restore_succeeded"] is True
    assert hou.set_frame_calls == [2.0, 23.25]


def test_frame_range_handlers_return_structured_data():
    output = _Node()
    hou = _HouStub(output)
    client = object.__new__(HoudiniMCP)

    with mock.patch.object(mcp_client, "hou", hou):
        result = client._tool_inspect_frame_range_risk({
            "node_path": output.path(), "frames": [1.0]
        })

    assert result["success"] is True
    assert result["data"]["risk_level"] == "low"