# -*- coding: utf-8 -*-
"""Tool schema and policy contract tests."""

import unittest
import sys
from unittest import mock

from houdini_agent.core.harness_policy_config import (
    HIGH_RISK_TOOLS,
    SCENE_MUTATION_TOOLS,
)

for name in ("requests", "trafilatura"):
    if name not in sys.modules:
        sys.modules[name] = mock.MagicMock(name=name)

from houdini_agent.utils.ai_client import HOUDINI_TOOLS
from houdini_agent.utils.tool_registry import ToolRegistry
from houdini_agent.utils.mcp.client import HoudiniMCP


class CoreToolContractTest(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register_core_tools(HOUDINI_TOOLS)

    def test_tool_schema_names_match_registry_names(self):
        for meta in self.registry._tools.values():
            with self.subTest(tool=meta.name):
                self.assertEqual(meta.schema.get("type"), "function")
                self.assertEqual(meta.schema.get("function", {}).get("name"), meta.name)

    def test_all_core_tools_have_descriptions(self):
        for meta in self.registry._tools.values():
            with self.subTest(tool=meta.name):
                description = meta.schema.get("function", {}).get("description", "")
                self.assertTrue(description.strip())

    def test_ask_mode_contains_only_readonly_core_tools(self):
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        for name in ask_names:
            with self.subTest(tool=name):
                tags = self.registry._tools[name].tags
                self.assertTrue("readonly" in tags or "task" in tags)

    def test_high_risk_core_tools_require_confirmation(self):
        core_names = set(self.registry._tools)
        for name in HIGH_RISK_TOOLS & core_names:
            with self.subTest(tool=name):
                self.assertTrue(self.registry._tools[name].requires_confirmation)
                self.assertEqual(self.registry._tools[name].risk_level, "high")

    def test_mutating_confirm_tools_do_not_leak_into_ask_mode(self):
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        confirmed_names = {
            meta.name for meta in self.registry._tools.values() if meta.requires_confirmation
        }
        self.assertFalse(confirmed_names & ask_names)

    def test_new_query_tools_are_registered_for_ask_mode(self):
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        for name in (
            "get_parameter_schema", "inspect_node", "get_node_connections",
            "suggest_connection", "preview_node_operation", "validate_node_network",
            "find_nodes", "get_geometry_summary", "get_scene_snapshot",
        ):
            with self.subTest(tool=name):
                self.assertIn(name, ask_names)

    def test_temporary_auto_validation_tool_is_registered_but_not_code_exec(self):
        core_names = set(self.registry._tools)

        self.assertIn("temporary_auto_validate_geometry", core_names)
        self.assertNotIn("temporary_auto_validate_geometry", HIGH_RISK_TOOLS)
        self.assertFalse(self.registry._tools["temporary_auto_validate_geometry"].requires_confirmation)

    def test_set_update_mode_tool_is_registered_but_not_code_exec(self):
        core_names = set(self.registry._tools)

        self.assertIn("set_update_mode", core_names)
        self.assertNotIn("set_update_mode", HIGH_RISK_TOOLS)
        self.assertTrue(self.registry._tools["set_update_mode"].requires_confirmation)
        description = self.registry._tools["set_update_mode"].schema["function"]["description"]
        self.assertIn("agent 工具", description)
        self.assertIn("不是 Houdini 原生 API", description)

    def test_node_operation_tools_are_registered(self):
        core_names = set(self.registry._tools)
        for name in (
            "connect_nodes", "disconnect_nodes", "set_node_flags", "layout_nodes",
            "cook_node", "create_named_null",
        ):
            with self.subTest(tool=name):
                self.assertIn(name, core_names)

    def test_schema_and_dispatch_contracts_model_internal_tools_explicitly(self):
        core_names = set(self.registry._tools)
        dispatch_names = set(HoudiniMCP._TOOL_DISPATCH)
        ai_internal_tools = {"web_search", "fetch_webpage", "add_todo", "update_todo"}
        non_mcp_internal_dispatch = {
            "set_display_flag", "get_node_inputs", "list_network_boxes",
            "get_node_positions", "get_node_card", "check_errors",
            "find_nodes_by_param", "list_children", "get_node_parameters",
        }

        self.assertEqual(core_names - dispatch_names, ai_internal_tools)
        self.assertEqual(dispatch_names - core_names, non_mcp_internal_dispatch)
        for name, handler_name in HoudiniMCP._TOOL_DISPATCH.items():
            with self.subTest(tool=name):
                self.assertTrue(callable(getattr(HoudiniMCP, handler_name, None)))

    def test_harness_mutations_are_registered_as_mutating_with_undo(self):
        core_names = set(self.registry._tools)
        for name in SCENE_MUTATION_TOOLS & core_names:
            with self.subTest(tool=name):
                semantics = self.registry.get_execution_semantics(name)
                self.assertTrue(semantics["mutating"])
                self.assertTrue(semantics["undo"])

    def test_plugins_cannot_replace_or_downgrade_core_metadata(self):
        before = self.registry.get_meta("delete_node")
        with self.assertRaises(Exception):
            self.registry.register(
                "delete_node",
                before.schema,
                source="plugin",
                plugin_name="downgrade",
                modes={"ask"},
                risk_level="low",
                mutating=False,
                undo=False,
            )

        after = self.registry.get_meta("delete_node")
        self.assertIs(after, before)
        self.assertEqual(after.risk_level, "high")
        self.assertTrue(after.mutating)
        self.assertTrue(after.undo)
        self.assertIn("delete_node", HIGH_RISK_TOOLS)
        self.assertTrue(after.requires_confirmation)

    def test_core_runtime_and_argument_facts_are_registered(self):
        self.assertEqual(self.registry.get_meta("execute_shell").runtime, "local")
        self.assertEqual(self.registry.get_meta("get_parameter_schema").required_args(), ("node_path",))
        self.assertEqual(self.registry.get_meta("get_parameter_schema").path_kinds["node_path"], "node")
        self.assertEqual(self.registry.get_meta("save_hip").path_kinds["file_path"], "file")


if __name__ == "__main__":
    unittest.main()