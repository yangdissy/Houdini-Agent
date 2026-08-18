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


class AIClientContextTrimTest(unittest.TestCase):
    @staticmethod
    def _tool_round(label, call_id):
        return [
            {"role": "user", "content": label},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "inspect_node", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": call_id, "content": "result " + ("x" * 400)},
            {"role": "assistant", "content": label + " complete"},
        ]

    def test_progressive_trim_keeps_recent_complete_round_and_tool_pairing(self):
        client = object.__new__(AIClient)
        messages = [{"role": "system", "content": "rules"}]
        messages.extend(self._tool_round("old", "old_call"))
        messages.extend(self._tool_round("middle", "middle_call"))
        messages.extend(self._tool_round("current", "current_call"))

        trimmed = client._progressive_trim(messages, [], trim_level=3, tools=[])

        self.assertEqual(trimmed[0], {"role": "system", "content": "rules"})
        self.assertIn("current", [m.get("content") for m in trimmed if m.get("role") == "user"])
        call_ids = {
            tc["id"]
            for message in trimmed
            for tc in message.get("tool_calls", [])
        }
        tool_ids = {
            message["tool_call_id"]
            for message in trimmed
            if message.get("role") == "tool"
        }
        self.assertEqual(call_ids, tool_ids)

    def test_progressive_trim_counts_tools_in_every_budget_check(self):
        client = object.__new__(AIClient)
        messages = [{"role": "system", "content": "rules"}]
        messages.extend(self._tool_round("old", "old_call"))
        messages.extend(self._tool_round("current", "current_call"))
        tools = [{"type": "function", "function": {"description": "schema"}}]
        seen_tools = []

        def count(actual_messages, actual_tools=None):
            seen_tools.append(actual_tools)
            return len(actual_messages) * 100 + (500 if actual_tools else 0)

        with mock.patch.object(client, "_estimate_messages_tokens", side_effect=count):
            client._progressive_trim(messages, [], trim_level=1, tools=tools)

        self.assertGreater(len(seen_tools), 1)
        self.assertTrue(all(actual_tools is tools for actual_tools in seen_tools))

    def test_agent_loop_http_413_retries_with_tools_aware_progressive_trim(self):
        client = object.__new__(AIClient)
        client._tool_executor = mock.Mock()
        client._stop_event = mock.Mock()
        client._stop_event.is_set.return_value = False
        client._get_streaming_tool_executor = mock.Mock()
        client._get_streaming_tool_executor.return_value.reset.return_value = None
        client._sanitize_working_messages = lambda messages: messages
        client._ensure_context_within_budget = lambda messages, tools, limit: None
        client._progressive_trim = mock.Mock(side_effect=lambda messages, history, **kwargs: messages)
        client.chat_stream = mock.Mock(side_effect=[
            iter([{"type": "error", "error": "HTTP 413 payload too large"}]),
            iter([{"type": "content", "content": "done"}, {"type": "done", "usage": {}}]),
        ])
        tools = [{"type": "function", "function": {"name": "inspect_node"}}]

        result = client.agent_loop_stream(
            messages=[{"role": "user", "content": "inspect"}],
            model="test-model",
            provider="test-provider",
            tools_override=tools,
            max_iterations=2,
            context_limit=10000,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(client.chat_stream.call_count, 2)
        self.assertIs(client._progressive_trim.call_args.kwargs["tools"], tools)
        self.assertEqual(client._progressive_trim.call_args.kwargs["trim_level"], 1)


if __name__ == "__main__":
    unittest.main()