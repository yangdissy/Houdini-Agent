"""Runtime selection tests for registry-backed tool dispatch."""

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
    assert '"executable": false' in result["result"]
    assert "读取必须遵循的方法说明" in result["result"]


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