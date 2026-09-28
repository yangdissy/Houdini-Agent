# -*- coding: utf-8 -*-
"""Characterization tests for the legacy external FastMCP surface."""

import unittest
import inspect
from pathlib import Path
from unittest.mock import patch

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs

_install_hou_stub()
_install_thirdparty_stubs()

from houdini_agent.utils.mcp import server
from houdini_agent.utils.mcp.external_adapter import ExternalMCPExecutionAdapter
from houdini_agent.utils.mcp.capabilities import build_external_tool_manifest
from houdini_agent.utils.mcp.settings import MCPSettings, read_settings
from houdini_agent.utils.tool_registry import ToolRegistry


class _FastMCPStub:
    def __init__(self):
        self.tools = {}

    def tool(self, function=None, **options):
        def register(candidate):
            name = options.get("name") or candidate.__name__
            self.tools[name] = candidate
            return candidate

        return register(function) if function is not None else register


class ExternalMCPServerBypassRegressionTest(unittest.TestCase):
    def test_legacy_parallel_tool_source_is_absent(self):
        source = Path(server.__file__).read_text(encoding="utf-8")

        self.assertNotIn("def _setup_fastmcp_tools", source)
        self.assertNotIn("def execute_python_code", source)
        self.assertNotIn("hou_core.", source)


class GovernedExternalMCPServerTest(unittest.TestCase):
    def setUp(self):
        self.previous_mcp = server.mcp
        server.mcp = _FastMCPStub()

    def tearDown(self):
        server.mcp = self.previous_mcp

    def test_governed_schema_is_health_only_by_default(self):
        server._setup_governed_fastmcp_tools(MCPSettings())

        self.assertEqual(set(server.mcp.tools), {"health"})
        self.assertNotIn("execute_python_code", server.mcp.tools)

    def test_startup_rejects_executable_allowlist_without_adapter(self):
        settings = MCPSettings(enabled=True, allowed_tools=("health", "inspect"))
        previous_adapter = server._external_adapter
        server._external_adapter = None
        try:
            with patch.object(server, "read_settings", return_value=settings), patch.dict(
                "sys.modules", {"fastmcp": type("Module", (), {"FastMCP": _FastMCPStub})()}
            ):
                result = server.ensure_mcp_running(auto_start=False)
        finally:
            server._external_adapter = previous_adapter

        self.assertFalse(result[0])
        self.assertIn("adapter", result[1])

    def test_startup_rejects_stopped_adapter(self):
        settings = MCPSettings(enabled=True, allowed_tools=("health", "inspect"))
        previous_adapter = server._external_adapter
        server._external_adapter = type("Adapter", (), {
            "is_shutdown": lambda self: True,
        })()
        try:
            with patch.object(server, "read_settings", return_value=settings), patch.dict(
                "sys.modules", {"fastmcp": type("Module", (), {"FastMCP": _FastMCPStub})()}
            ):
                result = server.ensure_mcp_running(auto_start=False)
        finally:
            server._external_adapter = previous_adapter

        self.assertFalse(result[0])
        self.assertIn("stopped", result[1].lower())

    def test_registry_schema_drives_dynamic_wrapper_signature(self):
        schema = {
            "type": "object",
            "properties": {
                "node_path": {"type": "string"},
                "page": {"type": "integer"},
                "include_hidden": {"type": "boolean"},
            },
            "required": ["node_path"],
        }

        wrapper = server._build_governed_tool_wrapper(
            "inspect", schema, lambda name, args: {"success": True, "args": args}
        )
        signature = inspect.signature(wrapper)

        self.assertEqual(list(signature.parameters), ["node_path", "page", "include_hidden"])
        self.assertIs(signature.parameters["node_path"].default, inspect.Parameter.empty)
        self.assertIsNone(signature.parameters["page"].default)
        self.assertIs(signature.parameters["node_path"].annotation, str)
        self.assertIs(signature.parameters["page"].annotation, int)
        self.assertIs(signature.parameters["include_hidden"].annotation, bool)
        self.assertEqual(wrapper("/obj", 2, True)["args"], {
            "node_path": "/obj", "page": 2, "include_hidden": True,
        })

    def test_only_explicit_visible_registry_tools_are_registered(self):
        registry = ToolRegistry()
        schema = {
            "type": "function",
            "function": {
                "name": "inspect",
                "description": "Inspect a node",
                "parameters": {
                    "type": "object",
                    "properties": {"node_path": {"type": "string"}},
                    "required": ["node_path"],
                },
            },
        }
        registry.register(
            "inspect", schema, modes={"ask"}, runtime="houdini",
            tags={"readonly"}, risk_level="low", requires_confirmation=False,
            external_mcp_visible=True,
        )
        registry.register(
            "hidden", {**schema, "function": {**schema["function"], "name": "hidden"}},
            modes={"ask"}, tags={"readonly"}, risk_level="low",
        )
        calls = []
        settings = MCPSettings(enabled=True, allowed_tools=("health", "inspect", "hidden"))
        manifest = build_external_tool_manifest(
            registry, dispatch={"inspect": "_tool_inspect"},
            allowed_tools=settings.allowed_tools,
        )
        adapter = ExternalMCPExecutionAdapter(
            settings=settings,
            registry=registry,
            policy_engine=type("Policy", (), {
                "decide": lambda self, *args: __import__(
                    "houdini_agent.core.harness_engine", fromlist=["ToolPolicyDecision"]
                ).ToolPolicyDecision(action="allow")
            })(),
            execute=lambda name, args: calls.append((name, args)) or {"success": True},
            session_id="session-1", username="artist",
            manifest=manifest,
            dispatcher=type("Dispatcher", (), {
                "_tool_inspect": lambda self, args: args,
            })(),
            executor=type("Executor", (), {
                "is_blocked": lambda self: False, "is_shutdown": lambda self: False,
            })(),
            hou_module=type("Hou", (), {
                "applicationVersionString": staticmethod(lambda: "21.0.440")
            })(),
            agent_version="1.5.3", sdk_version="2.0.0",
        )
        previous_adapter = server._external_adapter
        server._external_adapter = adapter
        try:
            with patch("houdini_agent.utils.tool_registry.get_tool_registry", return_value=registry):
                server._setup_governed_fastmcp_tools(adapter._settings)
        finally:
            server._external_adapter = previous_adapter

        self.assertEqual(set(server.mcp.tools), {
            "health", "session_info", "capabilities", "inspect",
        })
        self.assertEqual(server.mcp.tools["session_info"]()["session_id"], "session-1")
        self.assertEqual(server.mcp.tools["capabilities"]()["status"], "healthy")
        self.assertTrue(server.mcp.tools["inspect"]("/obj/geo1")["success"])
        self.assertEqual(calls, [("inspect", {"node_path": "/obj/geo1"})])

    def test_runtime_unavailable_tool_is_hidden_from_schema(self):
        registry = ToolRegistry()
        schema = {
            "type": "function",
            "function": {"name": "missing", "description": "missing", "parameters": {}},
        }
        registry.register(
            "missing", schema, modes={"ask"}, runtime="houdini",
            tags={"readonly"}, risk_level="low", external_mcp_visible=True,
        )
        settings = MCPSettings(enabled=True, allowed_tools=("health", "missing"))
        adapter = ExternalMCPExecutionAdapter(
            settings=settings,
            registry=registry,
            policy_engine=object(),
            execute=lambda *args: {"success": True},
            manifest=[{
                "name": "missing", "handler": "_tool_missing", "feature": None,
                "minimum_houdini_version": None,
            }],
            dispatcher=object(),
            executor=type("Executor", (), {
                "is_blocked": lambda self: False, "is_shutdown": lambda self: False,
            })(),
            hou_module=type("Hou", (), {
                "applicationVersionString": staticmethod(lambda: "21.0.440")
            })(),
            agent_version="1.5.3", sdk_version="2.0.0", session_id="session-1",
        )
        previous_adapter = server._external_adapter
        server._external_adapter = adapter
        try:
            with patch("houdini_agent.utils.tool_registry.get_tool_registry", return_value=registry):
                server._setup_governed_fastmcp_tools(settings)
        finally:
            server._external_adapter = previous_adapter

        self.assertNotIn("missing", server.mcp.tools)

    def test_registered_tools_freeze_read_and_write_modes(self):
        registry = ToolRegistry()
        for name, mutating, modes in (
            ("inspect", False, {"ask"}),
            ("mutate", True, {"agent"}),
        ):
            registry.register(
                name,
                {"type": "function", "function": {
                    "name": name, "description": name, "parameters": {},
                }},
                modes=modes,
                runtime="houdini",
                risk_level="normal" if mutating else "low",
                mutating=mutating,
                external_mcp_visible=True,
            )
        modes = []
        adapter = type("Adapter", (), {
            "manifest": (
                {"name": "inspect", "mutating": False},
                {"name": "mutate", "mutating": True},
            ),
            "capabilities": lambda self: {
                "available_tools": ["inspect", "mutate"],
                "status": "healthy",
            },
            "session_info": lambda self: {},
            "new_context": lambda self, mode: modes.append(mode) or mode,
            "execute": lambda self, context, name, arguments: {"success": True},
        })()
        previous_adapter = server._external_adapter
        server._external_adapter = adapter
        try:
            with patch("houdini_agent.utils.tool_registry.get_tool_registry", return_value=registry):
                server._setup_governed_fastmcp_tools(MCPSettings(
                    allowed_tools=("inspect", "mutate"), max_risk_level="normal",
                ))
            server.mcp.tools["inspect"]()
            server.mcp.tools["mutate"]()
        finally:
            server._external_adapter = previous_adapter

        self.assertEqual(modes, ["ask", "agent"])

    def test_connection_status_reports_not_started_and_executor_blocked(self):
        settings = MCPSettings(enabled=True)
        previous_thread = server.mcp_thread_handle
        previous_adapter = server._external_adapter
        try:
            server.mcp_thread_handle = None
            server._external_adapter = None
            with patch.object(server, "read_settings", return_value=settings):
                self.assertEqual(server.get_mcp_status()["state"], "not_started")

            server.mcp_thread_handle = type("Thread", (), {"is_alive": lambda self: True})()
            server._external_adapter = type("Adapter", (), {
                "capabilities": lambda self: {
                    "executor_state": "blocked",
                    "degradations": ["executor_blocked"],
                }
            })()
            with patch.object(server, "read_settings", return_value=settings):
                status = server.get_mcp_status()
                self.assertEqual(status["state"], "executor_blocked")
                self.assertEqual(status["degradations"], ["executor_blocked"])
        finally:
            server.mcp_thread_handle = previous_thread
            server._external_adapter = previous_adapter

    def test_stop_shuts_down_adapter_before_joining_server_thread(self):
        events = []
        adapter = type("Adapter", (), {
            "shutdown": lambda self: events.append("adapter_shutdown")
        })()
        class Thread:
            alive = True

            def is_alive(self):
                return self.alive

            def join(self, timeout=None):
                events.append("joined")
                self.alive = False

        thread = Thread()
        previous_thread = server.mcp_thread_handle
        previous_adapter = server._external_adapter
        try:
            server.mcp_thread_handle = thread
            server._external_adapter = adapter

            result = server.stop_mcp_server()

            self.assertTrue(result[0])
            self.assertEqual(events, ["adapter_shutdown", "joined"])
        finally:
            server.mcp_thread_handle = previous_thread
            server._external_adapter = previous_adapter


class ExternalMCPSettingsTest(unittest.TestCase):
    def test_defaults_are_disabled_loopback_and_readonly(self):
        settings = MCPSettings()

        self.assertFalse(settings.enabled)
        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.allowed_tools, (
            "health", "get_network_structure", "get_geometry_points",
            "get_geometry_primitives", "get_usd_prim_info", "get_usd_layer_stack",
            "get_top_network_status", "list_top_work_items", "get_top_errors",
            "read_selection",
        ))
        self.assertNotIn("execute_python", settings.allowed_tools)
        self.assertIn("execute_python", settings.denied_tools)
        self.assertIn("execute_shell", settings.denied_tools)
        self.assertIn("delete_node", settings.denied_tools)
        self.assertEqual(settings.max_risk_level, "low")
        self.assertEqual(settings.write_node_roots, ())

    def test_invalid_governance_values_fail_closed(self):
        invalid_configs = (
            {"mcp_enabled": "maybe"},
            {"mcp_max_calls_per_session": "many"},
            {"mcp_max_concurrent_calls": "0"},
            {"mcp_host": "0.0.0.0"},
            {"mcp_max_risk_level": "unrestricted"},
            {"mcp_write_node_roots": "obj/project"},
            {"mcp_write_node_roots": "/obj/project/../other"},
        )

        for config in invalid_configs:
            with self.subTest(config=config), patch(
                "houdini_agent.utils.mcp.settings._load_config",
                return_value=(config, "test.ini"),
            ):
                with self.assertRaises(ValueError):
                    read_settings()


if __name__ == "__main__":
    unittest.main()