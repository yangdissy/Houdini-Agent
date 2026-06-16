# -*- coding: utf-8 -*-
"""AIClient adaptive thinking hint tests."""

import unittest

from houdini_agent.utils.ai_client import AIClient


def _call(tool_name, args=None):
    return ("call_1", tool_name, args or {}, {})


class AIClientThinkingHintTest(unittest.TestCase):
    def test_simple_create_node_success_does_not_force_think(self):
        hint = AIClient._thinking_followup_hint(
            True,
            False,
            [_call("create_node", {"node_type": "box"})],
            [{"success": True, "result": "✓/obj/geo1/box1"}],
            1,
        )
        self.assertNotIn("必须以 <think>", hint)
        self.assertIn("直接简短总结", hint)

    def test_connect_nodes_success_uses_brief_hint_only(self):
        hint = AIClient._thinking_followup_hint(
            True,
            False,
            [_call("connect_nodes", {"from_path": "/obj/geo1/box1", "to_path": "/obj/geo1/null1"})],
            [{"success": True}],
            2,
        )
        self.assertNotIn("必须以 <think>", hint)
        self.assertIn("1-3 行简短 <think>", hint)

    def test_failed_tool_keeps_error_recovery_guidance(self):
        hint = AIClient._thinking_followup_hint(
            True,
            True,
            [_call("connect_nodes", {"from_path": "/obj/geo1/box1"})],
            [{"success": False, "error": "Missing required to_path"}],
            1,
        )
        self.assertIn("无需调用check_errors", hint)
        self.assertIn("修正参数", hint)
        self.assertNotIn("必须以 <think>", hint)

    def test_thinking_disabled_returns_no_hint(self):
        hint = AIClient._thinking_followup_hint(
            False,
            True,
            [_call("connect_nodes")],
            [{"success": False}],
            1,
        )
        self.assertEqual(hint, "")


if __name__ == "__main__":
    unittest.main()