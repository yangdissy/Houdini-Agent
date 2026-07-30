# -*- coding: utf-8 -*-
"""AIClient adaptive thinking hint tests."""

import unittest
import sys
from unittest import mock

if "requests" not in sys.modules:
    sys.modules["requests"] = mock.MagicMock(name="requests")

from houdini_agent.utils.ai_client import AIClient


def _call(tool_name, args=None):
    return ("call_1", tool_name, args or {}, {})


class AIClientThinkingHintTest(unittest.TestCase):
    def test_gpt5_models_use_default_temperature(self):
        self.assertTrue(AIClient.requires_temperature_one("gpt-5.5"))
        self.assertTrue(AIClient.requires_temperature_one("gpt-5.3-codex"))
        self.assertEqual(AIClient._payload_temperature("gpt-5.5", 0.17), 1)

    def test_legacy_kimi_k3_display_id_normalizes_to_api_model(self):
        self.assertEqual(AIClient._normalize_model_id("k3[1m]"), "k3")
        self.assertEqual(AIClient._normalize_model_id(" k3 "), "k3")
        self.assertTrue(AIClient.requires_temperature_one(AIClient._normalize_model_id("k3[1m]")))

    def test_regular_models_keep_clamped_temperature(self):
        self.assertFalse(AIClient.requires_temperature_one("chatgpt-4o-latest"))
        self.assertEqual(AIClient._payload_temperature("chatgpt-4o-latest", 1.7), 1.0)

    def test_deepseek_v4_detection_includes_siliconflow_names(self):
        cases = {
            "deepseek-v4-pro": (True, True),
            "deepseek-v4-flash": (True, False),
            "deepseek-ai/DeepSeek-V4-Pro": (True, True),
            "deepseek-ai/DeepSeek-V4-Flash": (True, False),
            "deepseek-ai/DeepSeek-R1": (False, False),
        }
        for model, expected in cases.items():
            with self.subTest(model=model):
                self.assertEqual(
                    (AIClient._is_deepseek_v4_model(model), AIClient._is_deepseek_v4_pro_model(model)),
                    expected,
                )

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

    def test_tool_result_compression_redacts_secrets_before_llm(self):
        client = object.__new__(AIClient)
        compressed = AIClient._compress_tool_result(
            client,
            "execute_shell",
            {"success": True, "result": "token=abc123456789\nsecret=sk-testsecret1234567890"},
        )
        self.assertIn("[REDACTED]", compressed)
        self.assertNotIn("abc123456789", compressed)
        self.assertNotIn("sk-testsecret", compressed)

    def test_tool_result_compression_normalizes_invalid_shape(self):
        client = object.__new__(AIClient)
        compressed = AIClient._compress_tool_result(client, "execute_shell", "bad result")
        self.assertIn("Invalid tool result type", compressed)

    def test_tool_result_compression_handles_structured_result(self):
        client = object.__new__(AIClient)

        compressed = AIClient._compress_tool_result(
            client,
            "temporary_auto_validate_geometry",
            {
                "success": True,
                "summary": "临时 Auto 验证完成: /obj/geo1/OUT points=4",
                "result": {"node_path": "/obj/geo1/OUT", "point_count": 4},
            },
        )

        self.assertIn("points=4", compressed)
        self.assertIn("/obj/geo1/OUT", compressed)

    def test_json_execution_profile_uses_tool_registry(self):
        registry_profile = {
            "async_tools": {"web_search", "custom_async"},
            "batch_readonly_tools": {"inspect_node", "custom_readonly"},
        }
        with mock.patch("houdini_agent.utils.tool_registry.get_tool_registry") as get_registry:
            get_registry.return_value.build_streaming_executor_profile.return_value = registry_profile

            profile = AIClient._build_tool_execution_profile()

        self.assertEqual(profile["async_tools"], {"web_search", "custom_async"})
        self.assertEqual(profile["batch_readonly_tools"], {"inspect_node", "custom_readonly"})
        self.assertIn("history_query_tools", profile)

    def test_json_execution_profile_falls_back_without_registry(self):
        with mock.patch("houdini_agent.utils.tool_registry.get_tool_registry", side_effect=RuntimeError("boom")):
            profile = AIClient._build_tool_execution_profile()

        self.assertIn("web_search", profile["async_tools"])
        self.assertIn("execute_shell", profile["async_tools"])
        self.assertIn("get_node_parameters", profile["batch_readonly_tools"])

    def test_history_query_tools_use_execution_profile(self):
        registry_profile = {
            "history_query_tools": {"inspect_node", "web_search"},
        }
        with mock.patch("houdini_agent.utils.tool_registry.get_tool_registry") as get_registry:
            get_registry.return_value.build_streaming_executor_profile.return_value = registry_profile

            query_tools = AIClient._history_query_tools()

        self.assertEqual(query_tools, {"inspect_node", "web_search"})

    def test_compression_tool_groups_use_execution_profile(self):
        registry_profile = {
            "compression_query_tools": {"inspect_node"},
            "compression_operation_tools": {"create_node"},
        }
        with mock.patch("houdini_agent.utils.tool_registry.get_tool_registry") as get_registry:
            get_registry.return_value.build_streaming_executor_profile.return_value = registry_profile

            query_tools, operation_tools = AIClient._compression_tool_groups()

        self.assertEqual(query_tools, {"inspect_node"})
        self.assertEqual(operation_tools, {"create_node"})

    def test_thinking_tool_groups_use_execution_profile(self):
        registry_profile = {
            "thinking_simple_success_tools": {"inspect_node"},
            "thinking_deep_tools": {"connect_nodes"},
        }
        with mock.patch("houdini_agent.utils.tool_registry.get_tool_registry") as get_registry:
            get_registry.return_value.build_streaming_executor_profile.return_value = registry_profile

            simple_tools, deep_tools = AIClient._thinking_tool_groups()

        self.assertEqual(simple_tools, {"inspect_node"})
        self.assertEqual(deep_tools, {"connect_nodes"})

    def test_loop_guidance_query_tools_use_execution_profile(self):
        registry_profile = {
            "loop_guidance_query_tools": {"get_parameter_schema"},
        }
        with mock.patch("houdini_agent.utils.tool_registry.get_tool_registry") as get_registry:
            get_registry.return_value.build_streaming_executor_profile.return_value = registry_profile

            query_tools = AIClient._loop_guidance_query_tools()

        self.assertEqual(query_tools, {"get_parameter_schema"})


if __name__ == "__main__":
    unittest.main()