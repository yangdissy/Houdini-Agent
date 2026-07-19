# -*- coding: utf-8 -*-
"""Harness V2 policy tests."""

import unittest

from houdini_agent.core.harness_engine import (
    HarnessToolPolicyEngine,
    build_tool_retry_key,
    sanitize_tool_result,
)
from houdini_agent.core.harness_policy_config import (
    CODE_EXEC_TOOLS,
    CONFIRM_TOOLS,
    DESTRUCTIVE_TOOLS,
    HIGH_RISK_TOOLS,
    SCENE_MUTATION_TOOLS,
)


class HarnessPolicyConfigTest(unittest.TestCase):
    def test_high_risk_groups_are_confirmed(self):
        self.assertTrue(DESTRUCTIVE_TOOLS <= HIGH_RISK_TOOLS)
        self.assertTrue(CODE_EXEC_TOOLS <= HIGH_RISK_TOOLS)
        self.assertTrue(HIGH_RISK_TOOLS <= CONFIRM_TOOLS)

    def test_scene_mutations_are_confirmed_but_not_all_high_risk(self):
        self.assertTrue(SCENE_MUTATION_TOOLS <= CONFIRM_TOOLS)
        self.assertIn("create_node", SCENE_MUTATION_TOOLS)
        self.assertNotIn("create_node", HIGH_RISK_TOOLS)


class HarnessToolPolicyEngineTest(unittest.TestCase):
    def setUp(self):
        self.policy = HarnessToolPolicyEngine()

    def test_ask_mode_denies_high_risk_tools(self):
        decision = self.policy.decide("execute_python", {"code": "print(1)"}, {"mode": "ask"})
        self.assertEqual(decision.action, "deny")
        self.assertIn("Ask mode", decision.reason)

    def test_agent_mode_allows_high_risk_without_confirm_mode(self):
        decision = self.policy.decide("execute_shell", {"command": "dir"}, {"mode": "agent"})
        self.assertEqual(decision.action, "allow")

    def test_confirm_mode_asks_for_high_risk_tool(self):
        decision = self.policy.decide(
            "execute_shell",
            {"command": "dir"},
            {"mode": "agent", "confirm_mode": True},
        )
        self.assertEqual(decision.action, "ask")
        self.assertIn("requires confirmation", decision.reason)

    def test_execute_tools_require_code_or_command(self):
        missing_code = self.policy.decide("execute_python", {}, {"mode": "agent"})
        self.assertEqual(missing_code.action, "deny")
        self.assertIn("code", missing_code.reason)

        missing_command = self.policy.decide("execute_shell", {}, {"mode": "agent"})
        self.assertEqual(missing_command.action, "deny")
        self.assertIn("command", missing_command.reason)

    def test_sensitive_argument_key_is_denied(self):
        decision = self.policy.decide(
            "execute_shell",
            {"command": "echo ok", "api_key": "sk-test-secret-value"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "deny")
        self.assertIn("sensitive argument", decision.reason)

    def test_sensitive_value_pattern_is_denied(self):
        decision = self.policy.decide(
            "execute_python",
            {"code": "token = 'abc12345678901234567890'\nprint('ok')"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "deny")
        self.assertIn("sensitive value", decision.reason)

    def test_dangerous_python_is_denied(self):
        decision = self.policy.decide(
            "execute_python",
            {"code": "import shutil\nshutil.rmtree('C:/tmp/demo')"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "deny")
        self.assertIn("dangerous Python", decision.reason)

    def test_dangerous_shell_is_denied(self):
        decision = self.policy.decide(
            "execute_shell",
            {"command": "Remove-Item C:/tmp/demo -Recurse"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "deny")
        self.assertIn("dangerous shell", decision.reason)

    def test_path_traversal_is_denied(self):
        decision = self.policy.decide(
            "get_node_parameters",
            {"node_path": "/obj/../out"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "deny")
        self.assertIn("path traversal", decision.reason)

    def test_unsupported_houdini_root_is_denied(self):
        decision = self.policy.decide(
            "get_node_parameters",
            {"node_path": "/etc/passwd"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "deny")
        self.assertIn("unsupported Houdini path root", decision.reason)

    def test_missing_node_path_is_denied(self):
        decision = self.policy.decide("get_node_parameters", {}, {"mode": "agent"})
        self.assertEqual(decision.action, "deny")
        self.assertIn("node_path", decision.reason)

    def test_new_readonly_tools_validate_houdini_paths(self):
        missing_schema_path = self.policy.decide("get_parameter_schema", {}, {"mode": "agent"})
        self.assertEqual(missing_schema_path.action, "deny")
        self.assertIn("node_path", missing_schema_path.reason)

        missing_inspect_path = self.policy.decide("inspect_node", {}, {"mode": "agent"})
        self.assertEqual(missing_inspect_path.action, "deny")
        self.assertIn("node_path", missing_inspect_path.reason)

        missing_connections_path = self.policy.decide("get_node_connections", {}, {"mode": "agent"})
        self.assertEqual(missing_connections_path.action, "deny")
        self.assertIn("node_path", missing_connections_path.reason)

        missing_geo_path = self.policy.decide("get_geometry_summary", {}, {"mode": "agent"})
        self.assertEqual(missing_geo_path.action, "deny")
        self.assertIn("node_path", missing_geo_path.reason)

        bad_inspect_root = self.policy.decide("inspect_node", {"node_path": "/etc"}, {"mode": "agent"})
        self.assertEqual(bad_inspect_root.action, "deny")
        self.assertIn("unsupported Houdini path root", bad_inspect_root.reason)

        bad_connections_root = self.policy.decide("get_node_connections", {"node_path": "/etc"}, {"mode": "agent"})
        self.assertEqual(bad_connections_root.action, "deny")
        self.assertIn("unsupported Houdini path root", bad_connections_root.reason)

        bad_root = self.policy.decide("find_nodes", {"root_path": "/etc"}, {"mode": "agent"})
        self.assertEqual(bad_root.action, "deny")
        self.assertIn("unsupported Houdini path root", bad_root.reason)

        bad_snapshot_root = self.policy.decide("get_scene_snapshot", {"root_path": "/etc"}, {"mode": "agent"})
        self.assertEqual(bad_snapshot_root.action, "deny")
        self.assertIn("unsupported Houdini path root", bad_snapshot_root.reason)

    def test_connect_nodes_requires_from_and_to_paths(self):
        decision = self.policy.decide(
            "connect_nodes",
            {"from_path": "/obj/geo1/box1", "to_path": "/obj/geo1/null1"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "allow")

        missing_from = self.policy.decide(
            "connect_nodes",
            {"to_path": "/obj/geo1/null1"},
            {"mode": "agent"},
        )
        self.assertEqual(missing_from.action, "deny")
        self.assertIn("from_path", missing_from.reason)

        missing_to = self.policy.decide(
            "connect_nodes",
            {"from_path": "/obj/geo1/box1"},
            {"mode": "agent"},
        )
        self.assertEqual(missing_to.action, "deny")
        self.assertIn("to_path", missing_to.reason)

    def test_suggest_connection_requires_from_and_to_paths(self):
        decision = self.policy.decide(
            "suggest_connection",
            {"from_path": "/obj/geo1/box1", "to_path": "/obj/geo1/null1"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "allow")

        missing_from = self.policy.decide("suggest_connection", {"to_path": "/obj/geo1/null1"}, {"mode": "agent"})
        self.assertEqual(missing_from.action, "deny")
        self.assertIn("from_path", missing_from.reason)

        missing_to = self.policy.decide("suggest_connection", {"from_path": "/obj/geo1/box1"}, {"mode": "agent"})
        self.assertEqual(missing_to.action, "deny")
        self.assertIn("to_path", missing_to.reason)

    def test_create_named_null_requires_name(self):
        missing_name = self.policy.decide("create_named_null", {}, {"mode": "agent"})
        self.assertEqual(missing_name.action, "deny")
        self.assertIn("name", missing_name.reason)

        bad_parent = self.policy.decide("create_named_null", {"name": "OUT_TEST", "parent_path": "/etc"}, {"mode": "agent"})
        self.assertEqual(bad_parent.action, "deny")
        self.assertIn("unsupported Houdini path root", bad_parent.reason)

    def test_cook_node_requires_valid_node_path(self):
        missing_path = self.policy.decide("cook_node", {}, {"mode": "agent"})
        self.assertEqual(missing_path.action, "deny")
        self.assertIn("node_path", missing_path.reason)

        bad_root = self.policy.decide("cook_node", {"node_path": "/etc"}, {"mode": "agent"})
        self.assertEqual(bad_root.action, "deny")
        self.assertIn("unsupported Houdini path root", bad_root.reason)

    def test_cook_node_without_force_is_allowed_in_agent(self):
        decision = self.policy.decide(
            "cook_node",
            {"node_path": "/obj/geo1/OUT"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "allow")

    def test_cook_node_force_requires_confirmation(self):
        decision = self.policy.decide(
            "cook_node",
            {"node_path": "/obj/geo1/OUT", "force": True},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "ask")
        self.assertIn("cook_node force", decision.reason)

    def test_node_paths_are_normalized(self):
        decision = self.policy.decide(
            "get_node_parameters",
            {"node_path": " //obj//geo1 "},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "allow")
        self.assertEqual(decision.patched_args["node_path"], "/obj/geo1")

    def test_save_hip_path_gets_extension_retry(self):
        decision = self.policy.decide(
            "save_hip",
            {"output_path": "/tmp/shot_v001"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "retry")
        self.assertEqual(decision.patched_args["output_path"], "/tmp/shot_v001.hip")

    def test_retry_key_is_stable_for_equal_args(self):
        left = build_tool_retry_key("set_node_parameter", {"b": 2, "a": 1})
        right = build_tool_retry_key("set_node_parameter", {"a": 1, "b": 2})
        self.assertEqual(left, right)


class HarnessToolOutputGuardrailTest(unittest.TestCase):
    def test_non_dict_result_becomes_error_contract(self):
        sanitized = sanitize_tool_result("plain text")
        self.assertFalse(sanitized["success"])
        self.assertIn("Invalid tool result type", sanitized["error"])

    def test_success_result_is_redacted_recursively(self):
        sanitized = sanitize_tool_result({
            "success": True,
            "result": "api_key=sk-testsecret1234567890",
            "metadata": {"token": "abc123456789"},
        })
        self.assertTrue(sanitized["success"])
        self.assertIn("[REDACTED]", sanitized["result"])
        self.assertEqual(sanitized["metadata"]["token"], "[REDACTED]")
        self.assertNotIn("sk-testsecret", str(sanitized))

    def test_failure_without_error_gets_error_message(self):
        sanitized = sanitize_tool_result({"success": False, "result": "failed with password=abc123"})
        self.assertFalse(sanitized["success"])
        self.assertIn("[REDACTED]", sanitized["error"])


if __name__ == "__main__":
    unittest.main()