# -*- coding: utf-8 -*-
"""Harness V2 policy tests."""

import unittest

from houdini_agent.core.harness_engine import (
    HarnessToolPolicyEngine,
    build_tool_retry_key,
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

    def test_missing_node_path_is_denied(self):
        decision = self.policy.decide("get_node_parameters", {}, {"mode": "agent"})
        self.assertEqual(decision.action, "deny")
        self.assertIn("node_path", decision.reason)

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

    def test_get_node_inputs_requires_node_type_not_node_path(self):
        decision = self.policy.decide(
            "get_node_inputs",
            {"node_type": "null", "category": "sop"},
            {"mode": "agent"},
        )
        self.assertEqual(decision.action, "allow")

        missing_type = self.policy.decide("get_node_inputs", {"category": "sop"}, {"mode": "agent"})
        self.assertEqual(missing_type.action, "deny")
        self.assertIn("node_type", missing_type.reason)

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


if __name__ == "__main__":
    unittest.main()