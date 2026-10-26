"""Runtime selection tests for registry-backed tool dispatch."""

import json
import sys
from types import SimpleNamespace
from unittest import mock

sys.modules.setdefault("requests", mock.MagicMock(name="requests"))

from houdini_agent.utils.tool_registry import ToolRegistry, resolve_tool_runtime
from houdini_agent.utils.mcp.client import HoudiniMCP


def _schema(name):
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {}}}


def test_resolver_uses_registered_local_runtime():
    registry = mock.Mock()
    registry.get_meta.return_value = SimpleNamespace(runtime="local")

    assert resolve_tool_runtime(registry, "list_skills") == "local"


def test_resolver_uses_registered_houdini_runtime():
    registry = mock.Mock()
    registry.get_meta.return_value = SimpleNamespace(runtime="houdini")

    assert resolve_tool_runtime(registry, "inspect_node") == "houdini"


def test_unknown_tool_defaults_to_houdini():
    registry = mock.Mock()
    registry.get_meta.return_value = None

    assert resolve_tool_runtime(registry, "missing") == "houdini"


def test_default_registration_separates_list_and_run_skill_runtimes():
    registry = ToolRegistry()
    registry.register_core_tools([_schema("list_skills"), _schema("run_skill")])

    assert resolve_tool_runtime(registry, "list_skills") == "local"
    assert resolve_tool_runtime(registry, "run_skill") == "houdini"


def test_mcp_dispatch_uses_registered_runtime_for_list_skills():
    registry = ToolRegistry()
    registry.register_core_tools([_schema("list_skills")])
    client = HoudiniMCP()

    with mock.patch(
        "houdini_agent.utils.tool_registry.get_tool_registry", return_value=registry
    ), mock.patch.object(
        client, "_tool_list_skills", return_value={"success": True, "result": "skills"}
    ) as handler:
        result = client.execute_tool("list_skills", {}, mode="agent")

    assert result == {"success": True, "result": "skills"}
    handler.assert_called_once_with({})


def test_list_skills_marks_instructions_only_usage():
    client = HoudiniMCP()
    listed = [{
        "name": "decompose_houdini_task",
        "category": "workflow",
        "description": "Decompose complex Houdini work.",
        "risk_level": "low",
        "parameters": {},
        "executable": False,
    }]

    with mock.patch("houdini_agent.utils.mcp.client._list_skills", return_value=listed):
        result = client._tool_list_skills({"query": "复杂 Houdini 任务"})

    assert result["success"] is True
    payload = json.loads(result["result"].split("\n\n", 1)[1])
    assert payload["workflow"][0]["executable"] is False
    assert "读取必须遵循的方法说明" in result["result"]


def test_list_skills_preserves_parameter_contract_in_compact_output():
    client = HoudiniMCP()
    parameters = {
        "node_path": {"type": "string", "description": "Target node.", "required": True},
        "limit": {
            "type": "integer", "description": "Result limit.",
            "default": 0, "minimum": 0, "maximum": 10,
        },
        "mode": {
            "type": "string", "description": "Analysis mode.",
            "default": "fast", "enum": ["fast", "full"],
        },
        "enabled": {"type": "boolean", "description": "Include details.", "default": False},
        "selector": {"type": ["integer", "string"], "description": "Index or name."},
        "attributes": {
            "type": "array", "description": "Attribute names.",
            "default": [], "items": {"type": "string"},
        },
    }
    listed = [{
        "name": "contract_test",
        "category": "geometry",
        "description": "Analyze selected attributes.",
        "risk_level": "low",
        "parameters": parameters,
        "executable": True,
    }]
    expected = {
        "geometry": [{
            "name": "contract_test",
            "description": "Analyze selected attributes.",
            "risk_level": "low",
            "executable": True,
            "parameters": [
                {**definition, "name": name, "required": bool(definition.get("required", False))}
                for name, definition in parameters.items()
            ],
        }],
    }

    with mock.patch("houdini_agent.utils.mcp.client._list_skills", return_value=listed) as discover:
        result = client._tool_list_skills({"category": "geometry", "query": "attributes", "limit": 1})

    discover.assert_called_once_with(category="geometry", query="attributes", limit=1)
    assert result["success"] is True
    payload_text = result["result"].split("\n\n", 1)[1]
    assert json.loads(payload_text) == expected
    assert payload_text == json.dumps(expected, ensure_ascii=False, separators=(",", ":"))


def test_list_skills_empty_results_keep_discovery_feedback():
    client = HoudiniMCP()
    cases = [
        ({}, "当前没有可用的 Skill。"),
        ({"category": "geometry"}, "分类 'geometry' 下没有可用的 Skill。"),
        ({"query": "unmatched request"}, "没有找到与 'unmatched request' 相关的 Skill。"),
    ]

    for args, expected in cases:
        with mock.patch("houdini_agent.utils.mcp.client._list_skills", return_value=[]):
            result = client._tool_list_skills(args)

        assert result == {"success": True, "result": expected}


def test_mcp_set_user_binds_skill_registry_user():
    client = HoudiniMCP()

    with mock.patch("houdini_agent.skills.set_current_user") as set_current_user:
        client.set_user("artist_one")

    set_current_user.assert_called_once_with("artist_one")


def test_run_skill_rebinds_mcp_user_before_execution():
    client = HoudiniMCP()
    client._username = "artist_one"

    with mock.patch("houdini_agent.skills.set_current_user") as set_current_user, mock.patch(
        "houdini_agent.utils.mcp.client._run_skill",
        return_value={"mode": "preview", "installed": False},
    ):
        result = client._tool_run_skill(
            {"skill_name": "install_houdini_skill", "params": {"mode": "preview"}}
        )

    set_current_user.assert_called_once_with("artist_one")
    assert result["success"] is True