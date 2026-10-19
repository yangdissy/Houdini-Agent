# -*- coding: utf-8 -*-
"""Tool schema and policy contract tests."""

import unittest
import sys
from pathlib import Path
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
from houdini_agent.utils.mcp.client import HoudiniMCP, format_tool_usage_from_schema


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

    def test_execute_python_confirmation_follows_harness_policy(self):
        description = self.registry.get_meta("execute_python").schema["function"]["description"]

        self.assertNotIn("需要用户确认", description)
        self.assertIn("确认模式", description)

    def test_execute_python_allows_governed_fallback_for_missing_scene_capabilities(self):
        description = self.registry.get_meta("execute_python").schema["function"]["description"]

        self.assertNotIn("禁止使用场景：1)节点/参数操作", description)
        self.assertIn("Spare Parameter", description)
        self.assertIn("ParmTemplateGroup", description)
        self.assertIn("必须直接调用 execute_python", description)
        self.assertIn("不属于绕过治理", description)

    def test_scene_tool_guidance_does_not_request_prose_confirmation(self):
        root = Path(__file__).resolve().parents[1]
        security_rules = (root / "rules" / "security_boundaries.md").read_text(encoding="utf-8")
        main_rules = (root / "rules" / "MainRules.md").read_text(encoding="utf-8")
        work_rules = (root / "rules" / "houdini_work_discipline.md").read_text(encoding="utf-8")

        forbidden = (
            "执行代码前，必须先向用户说明将要执行的具体操作，确认后再运行",
            "执行前必须告知用户将删除的节点名称并得到确认",
            "执行前须列出将影响的节点范围，得到用户确认后再运行",
            "如需要请求确认",
        )
        combined_rules = security_rules + main_rules + work_rules
        for phrase in forbidden:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, combined_rules)

        for tool_name in ("insert_multiparm_instance", "remove_multiparm_instance"):
            with self.subTest(tool=tool_name):
                description = self.registry.get_meta(tool_name).schema["function"]["description"]
                self.assertNotIn("需要确认", description)
                self.assertIn("Harness", description)

            self.assertIn("Spare Parameter", work_rules)
            self.assertIn("不属于绕过治理", work_rules)

    def test_usage_hints_are_generated_from_schema_parameter_names(self):
        for tool_name in ("create_wrangle_node", "semantic_search_nodes"):
            with self.subTest(tool=tool_name):
                meta = self.registry.get_meta(tool_name)
                usage = format_tool_usage_from_schema(meta.schema)
                properties = meta.schema["function"]["parameters"]["properties"]
                for parameter_name in properties:
                    self.assertIn(parameter_name + "=", usage)

        wrangle_usage = format_tool_usage_from_schema(
            self.registry.get_meta("create_wrangle_node").schema
        )
        semantic_usage = format_tool_usage_from_schema(
            self.registry.get_meta("semantic_search_nodes").schema
        )
        self.assertIn("vex_code=", wrangle_usage)
        self.assertIn("node_name=", wrangle_usage)
        self.assertNotIn(" code=", wrangle_usage)
        self.assertIn("description=", semantic_usage)
        self.assertNotIn("query=", semantic_usage)

    def test_ask_mode_contains_only_readonly_or_controlled_state_tools(self):
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        controlled_state_tools = {
            "temporary_auto_validate_geometry",
            "perf_start_profile",
            "perf_stop_and_report",
        }
        for name in ask_names:
            with self.subTest(tool=name):
                tags = self.registry._tools[name].tags
                self.assertTrue(
                    "readonly" in tags or "task" in tags or name in controlled_state_tools
                )

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
            "build_pdg_expression", "find_parameter_references", "list_multiparm_instances",
        ):
            with self.subTest(tool=name):
                self.assertIn(name, ask_names)

    def test_temporary_auto_validation_tool_is_registered_but_not_code_exec(self):
        core_names = set(self.registry._tools)

        self.assertIn("temporary_auto_validate_geometry", core_names)
        self.assertNotIn("temporary_auto_validate_geometry", HIGH_RISK_TOOLS)
        self.assertFalse(self.registry._tools["temporary_auto_validate_geometry"].requires_confirmation)
        profile = self.registry.build_streaming_executor_profile()
        self.assertNotIn("temporary_auto_validate_geometry", profile["batch_readonly_tools"])
        self.assertIn("temporary_auto_validate_geometry", profile["execution_barrier_tools"])

    def test_perf_tools_are_stateful_execution_barriers(self):
        profile = self.registry.build_streaming_executor_profile()
        for name in ("perf_start_profile", "perf_stop_and_report"):
            with self.subTest(tool=name):
                self.assertNotIn(name, profile["batch_readonly_tools"])
                self.assertIn(name, profile["execution_barrier_tools"])

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

    def test_pdg_expression_tool_has_callable_dispatch(self):
        self.assertIn("build_pdg_expression", self.registry._tools)
        handler_name = HoudiniMCP._TOOL_DISPATCH.get("build_pdg_expression")
        self.assertTrue(handler_name)
        self.assertTrue(callable(getattr(HoudiniMCP, handler_name, None)))

    def test_parameter_reference_tool_has_callable_dispatch(self):
        self.assertIn("find_parameter_references", self.registry._tools)
        handler_name = HoudiniMCP._TOOL_DISPATCH.get("find_parameter_references")
        self.assertTrue(handler_name)
        self.assertTrue(callable(getattr(HoudiniMCP, handler_name, None)))

    def test_set_parameter_reference_is_governed_mutation(self):
        self.assertIn("set_parameter_reference", SCENE_MUTATION_TOOLS)
        meta = self.registry._tools["set_parameter_reference"]
        self.assertTrue(meta.requires_confirmation)
        self.assertTrue(meta.undo)
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        self.assertNotIn("set_parameter_reference", ask_names)
        handler_name = HoudiniMCP._TOOL_DISPATCH.get("set_parameter_reference")
        self.assertTrue(callable(getattr(HoudiniMCP, handler_name, None)))

    def test_multiparm_list_tool_has_callable_dispatch(self):
        self.assertIn("list_multiparm_instances", self.registry._tools)
        handler_name = HoudiniMCP._TOOL_DISPATCH.get("list_multiparm_instances")
        self.assertTrue(handler_name)
        self.assertTrue(callable(getattr(HoudiniMCP, handler_name, None)))

    def test_multiparm_insert_tool_is_governed_mutation(self):
        self.assertIn("insert_multiparm_instance", SCENE_MUTATION_TOOLS)
        meta = self.registry._tools["insert_multiparm_instance"]
        self.assertTrue(meta.requires_confirmation)
        self.assertTrue(meta.undo)
        self.assertTrue(meta.mutating)
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        self.assertNotIn("insert_multiparm_instance", ask_names)
        handler_name = HoudiniMCP._TOOL_DISPATCH.get("insert_multiparm_instance")
        self.assertTrue(callable(getattr(HoudiniMCP, handler_name, None)))

    def test_spare_parameter_tool_is_governed_mutation(self):
        self.assertIn("upsert_spare_parameter", SCENE_MUTATION_TOOLS)
        meta = self.registry._tools["upsert_spare_parameter"]
        properties = meta.schema["function"]["parameters"]["properties"]
        self.assertEqual(
            set(properties["parameter_type"]["enum"]),
            {"float", "int", "toggle", "string", "menu", "vector2", "vector3", "vector4", "color"},
        )
        self.assertIn("menu_items", properties)
        self.assertIn("menu_labels", properties)
        self.assertIn("size", properties)
        self.assertTrue(meta.requires_confirmation)
        self.assertTrue(meta.undo)
        self.assertTrue(meta.mutating)
        self.assertEqual(meta.path_kinds["node_path"], "node")
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        self.assertNotIn("upsert_spare_parameter", ask_names)
        handler_name = HoudiniMCP._TOOL_DISPATCH.get("upsert_spare_parameter")
        self.assertTrue(callable(getattr(HoudiniMCP, handler_name, None)))

    def test_multiparm_remove_tool_is_governed_mutation(self):
        self.assertIn("remove_multiparm_instance", SCENE_MUTATION_TOOLS)
        meta = self.registry._tools["remove_multiparm_instance"]
        self.assertTrue(meta.requires_confirmation)
        self.assertTrue(meta.undo)
        self.assertTrue(meta.mutating)
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        self.assertNotIn("remove_multiparm_instance", ask_names)
        handler_name = HoudiniMCP._TOOL_DISPATCH.get("remove_multiparm_instance")
        self.assertTrue(callable(getattr(HoudiniMCP, handler_name, None)))

    def test_object_merge_batch_tool_is_governed_mutation(self):
        self.assertIn("create_object_merges_batch", SCENE_MUTATION_TOOLS)
        meta = self.registry._tools["create_object_merges_batch"]
        self.assertTrue(meta.requires_confirmation)
        self.assertTrue(meta.undo)
        self.assertTrue(meta.mutating)
        self.assertEqual(meta.path_kinds["parent_path"], "node")
        self.assertEqual(meta.path_kinds["source_paths"], "node")
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        self.assertNotIn("create_object_merges_batch", ask_names)
        handler_name = HoudiniMCP._TOOL_DISPATCH.get("create_object_merges_batch")
        self.assertTrue(callable(getattr(HoudiniMCP, handler_name, None)))

    def test_schema_and_dispatch_contracts_model_internal_tools_explicitly(self):
        core_names = set(self.registry._tools)
        dispatch_names = set(HoudiniMCP._TOOL_DISPATCH)
        ai_internal_tools = {
            "web_search", "fetch_webpage", "add_todo", "update_todo",
            "get_operation_status", "list_operation_receipts",
            "inspect_tool_contract", "search_tool_contracts", "read_tool_result",
        }
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
        for name in (
            "get_operation_status", "list_operation_receipts",
            "inspect_tool_contract", "search_tool_contracts", "read_tool_result",
        ):
            with self.subTest(tool=name):
                meta = self.registry.get_meta(name)
                self.assertEqual(meta.runtime, "local")
                self.assertEqual(meta.risk_level, "low")
                self.assertFalse(meta.requires_confirmation)
                self.assertFalse(meta.mutating)
                self.assertFalse(meta.undo)


if __name__ == "__main__":
    unittest.main()