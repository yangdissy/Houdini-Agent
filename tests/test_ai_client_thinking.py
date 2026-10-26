# -*- coding: utf-8 -*-
"""AIClient adaptive thinking hint tests."""

import unittest
import sys
import json
import tempfile
import threading
from pathlib import Path
from unittest import mock

if "requests" not in sys.modules:
    sys.modules["requests"] = mock.MagicMock(name="requests")

from houdini_agent.utils.ai_client import AIClient
from houdini_agent.utils.embedding import LocalEmbedder
from houdini_agent.core.tool_result_store import ToolResultStore


def _call(tool_name, args=None):
    return ("call_1", tool_name, args or {}, {})


class AIClientThinkingHintTest(unittest.TestCase):
    def test_json_discovery_refreshes_one_tool_prompt_and_rejects_early_call(self):
        import copy
        from houdini_agent.core.agent_request_assembly import ToolExposureState
        from houdini_agent.utils.tool_registry import ToolRegistry

        registry = ToolRegistry()
        schemas = [{"type": "function", "function": {"name": name, "description": name, "parameters": {}}}
                   for name in ("search_tool_contracts", "get_usd_prim_info")]
        registry.register_core_tools(schemas)
        exposure = ToolExposureState(registry, schemas[:1])
        search = '```json\n{"tool":"search_tool_contracts","args":{"query":"get_usd_prim_info","load":true}}\n```'
        inspect = '```json\n{"tool":"get_usd_prim_info","args":{}}\n```'
        responses = iter([search + '\n' + inspect, inspect, "Complete."])
        requests = []
        calls = []
        client = self._loop_client([])
        client._batch_tool_executor = None
        client._tool_executor = lambda name, **args: (
            exposure.load(args["query"]) if name == "search_tool_contracts"
            else calls.append(name) or {"success": True, "result": "inspected"}
        )

        def stream(**kwargs):
            requests.append(copy.deepcopy(kwargs["messages"]))
            return iter([{"type": "content", "content": next(responses)}, {"type": "done", "usage": {}}])

        client.chat_stream = stream
        result = client.agent_loop_json_mode(
            messages=[{"role": "user", "content": "inspect USD"}], tools_override=schemas[:1],
            tool_exposure=exposure, model="test-model", provider="test-provider",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["get_usd_prim_info"])
        first_prompts = [message["content"] for message in requests[0] if message["role"] == "system"]
        second_prompts = [message["content"] for message in requests[1] if message["role"] == "system"]
        self.assertNotIn("**get_usd_prim_info**", '\n'.join(first_prompts))
        self.assertIn("**get_usd_prim_info**", '\n'.join(second_prompts))
        self.assertEqual(sum(prompt.count("## 可用工具") for prompt in second_prompts), 1)

    def test_native_discovery_refreshes_schemas_only_after_current_response(self):
        from houdini_agent.core.agent_request_assembly import ToolExposureState
        from houdini_agent.core.streaming_tool_executor import StreamingToolExecutor
        from houdini_agent.utils.tool_registry import ToolRegistry

        registry = ToolRegistry()
        schemas = [{"type": "function", "function": {"name": name, "description": name, "parameters": {}}}
                   for name in ("search_tool_contracts", "get_usd_prim_info")]
        registry.register_core_tools(schemas)
        exposure = ToolExposureState(registry, schemas[:1])
        search = {"type": "tool_call", "tool_call": {
            "id": "search-1", "type": "function", "function": {
                "name": "search_tool_contracts", "arguments": '{"query":"get_usd_prim_info","load":true}',
            },
        }}
        guessed = self._tool_call_chunk("guessed", "get_usd_prim_info")
        allowed = self._tool_call_chunk("allowed", "get_usd_prim_info")
        client = self._loop_client([
            [search, guessed, {"type": "done", "usage": {}}],
            [allowed, {"type": "done", "usage": {}}],
            [{"type": "content", "content": "Complete."}, {"type": "done", "usage": {}}],
        ])
        calls = []
        client._tool_executor = lambda name, **args: (
            exposure.load(args["query"]) if name == "search_tool_contracts"
            else calls.append(name) or {"success": True, "result": "inspected"}
        )
        client._get_streaming_tool_executor.return_value = StreamingToolExecutor(
            lambda name, args: client._tool_executor(name, **args), lambda args: {}, lambda args: {},
        )

        result = client.agent_loop_stream(
            messages=[{"role": "user", "content": "inspect USD"}], tool_exposure=exposure,
            tools_override=schemas[:1], model="test-model", provider="test-provider",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["get_usd_prim_info"])
        requests = client.chat_stream.call_args_list
        self.assertEqual([tool["function"]["name"] for tool in requests[0].kwargs["tools"]], ["search_tool_contracts"])
        self.assertIn("get_usd_prim_info", {tool["function"]["name"] for tool in requests[1].kwargs["tools"]})
        guessed_result = next(message for message in result["new_messages"] if message.get("tool_call_id") == "guessed")
        self.assertIn("tool_not_exposed", guessed_result["content"])

    @staticmethod
    def _loop_client(streams):
        client = object.__new__(AIClient)
        client._tool_executor = mock.Mock()
        client._tool_executor.execute.return_value = {"success": True}
        client._stop_event = mock.Mock()
        client._stop_event.is_set.return_value = False
        client._stop_event.wait.return_value = False
        client._get_streaming_tool_executor = mock.Mock()
        stream_executor = client._get_streaming_tool_executor.return_value
        stream_executor.reset.return_value = None
        stream_executor.execute_round.return_value = {
            "results_ordered": [{"success": True}],
            "dedup_flags": [False],
            "early_skip_count": 0,
        }
        client._sanitize_working_messages = lambda messages: messages
        client._ensure_context_within_budget = lambda messages, tools, limit: None
        client.chat_stream = mock.Mock(side_effect=[iter(stream) for stream in streams])
        return client

    def test_agent_loop_rechecks_once_after_tools_before_finishing(self):
        client = self._loop_client([
            [
                {"type": "tool_call", "tool_call": {
                    "id": "call_1", "type": "function",
                    "function": {"name": "inspect_node", "arguments": "{}"},
                }},
                {"type": "done", "usage": {}},
            ],
            [{"type": "content", "content": "Next I will verify."}, {"type": "done", "usage": {}}],
            [{"type": "content", "content": "Complete."}, {"type": "done", "usage": {}}],
        ])
        resume = mock.Mock(side_effect=["Check completion and continue if needed", None])

        result = client.agent_loop_stream(
            messages=[{"role": "user", "content": "inspect and verify"}],
            model="test-model",
            provider="test-provider",
            tools_override=[{"type": "function", "function": {"name": "inspect_node"}}],
            on_incomplete=resume,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(client.chat_stream.call_count, 3)
        self.assertEqual(resume.call_count, 2)
        self.assertEqual(result["final_content"].strip(), "Complete.")

    def test_agent_loop_does_not_recheck_first_round_plain_answer(self):
        client = self._loop_client([
            [{"type": "content", "content": "Answer."}, {"type": "done", "usage": {}}],
        ])
        resume = mock.Mock(return_value="continue")

        result = client.agent_loop_stream(
            messages=[{"role": "user", "content": "question"}],
            model="test-model",
            provider="test-provider",
            tools_override=[],
            on_incomplete=resume,
        )

        self.assertTrue(result["ok"])
        resume.assert_not_called()
        self.assertEqual(client.chat_stream.call_count, 1)

    @staticmethod
    def _tool_call_chunk(call_id, name="inspect_node"):
        return {"type": "tool_call", "tool_call": {
            "id": call_id, "type": "function",
            "function": {"name": name, "arguments": "{}"},
        }}

    def test_agent_loop_thinking_tracks_recovery_and_resets_after_success(self):
        cases = [
            (True, 0, [True, False]),
            (True, 1, [True, True, False]),
            (True, 2, [True, True, True, False]),
            (False, 0, [False, False]),
            (False, 1, [False, False, False]),
            (False, 2, [False, False, False, False]),
        ]
        for enabled, retry_count, expected in cases:
            with self.subTest(enabled=enabled, retry_count=retry_count):
                streams = [
                    [{"type": "error", "error": "context_length_exceeded"}]
                    for _ in range(retry_count)
                ]
                streams.extend([
                    [self._tool_call_chunk("a"), {"type": "done", "usage": {}}],
                    [{"type": "content", "content": "Complete."}, {"type": "done", "usage": {}}],
                ])
                client = self._loop_client(streams)
                client._progressive_trim = mock.Mock(
                    side_effect=lambda messages, *args, **kwargs: messages
                )

                result = client.agent_loop_stream(
                    messages=[{"role": "user", "content": "inspect"}],
                    model="test-model",
                    provider="test-provider",
                    tools_override=[],
                    enable_thinking=enabled,
                )

                self.assertTrue(result["ok"])
                self.assertEqual(
                    [call.kwargs["enable_thinking"] for call in client.chat_stream.call_args_list],
                    expected,
                )
                self.assertEqual(len(result["tool_calls_history"]), 1)

    def test_agent_loop_backoff_can_stop_without_losing_completed_work(self):
        for stop_after in (1, 2, 3, None):
            with self.subTest(stop_after=stop_after):
                client = self._loop_client([
                    [self._tool_call_chunk("a"), {"type": "done", "usage": {
                        "prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
                    }}],
                    *[
                        [
                            {"type": "content", "content": f"Attempt {attempt}."},
                            {"type": "error", "error": "HTTP 503 service unavailable"},
                        ]
                        for attempt in (1, 2, 3)
                    ],
                    [{"type": "content", "content": "Complete."}, {"type": "done", "usage": {}}],
                ])
                client._progressive_trim = mock.Mock(
                    side_effect=lambda messages, *args, **kwargs: messages
                )

                def wait_for_retry(timeout):
                    if client._stop_event.wait.call_count == stop_after:
                        client._stop_event.is_set.return_value = True
                        return True
                    return False

                client._stop_event.wait.side_effect = wait_for_retry
                with mock.patch("houdini_agent.utils.ai_client.time.sleep") as sleep:
                    result = client.agent_loop_stream(
                        messages=[{"role": "user", "content": "inspect"}],
                        model="test-model",
                        provider="test-provider",
                        tools_override=[],
                        max_iterations=4 if stop_after else 5,
                    )

                attempts = stop_after or 3
                self.assertEqual(
                    client._stop_event.wait.call_args_list,
                    [mock.call(timeout) for timeout in (5, 10, 15)[:attempts]],
                )
                sleep.assert_not_called()
                self.assertEqual(len(result["tool_calls_history"]), 1)
                tool_messages = [message for message in result["new_messages"] if message["role"] == "tool"]
                self.assertEqual([message["tool_call_id"] for message in tool_messages], ["a"])
                self.assertEqual(result["usage"]["total_tokens"], 18)
                if stop_after:
                    self.assertFalse(result["ok"])
                    self.assertTrue(result["stopped"])
                    self.assertNotIn("stop_reason", result)
                    self.assertEqual(result["content"], "\n\n".join(
                        f"Attempt {attempt}." for attempt in range(1, stop_after + 1)
                    ))
                    self.assertEqual(result["final_content"].strip(), f"Attempt {stop_after}.")
                    self.assertEqual(client.chat_stream.call_count, stop_after + 1)
                    self.assertEqual(client._progressive_trim.call_count, max(0, stop_after - 2))
                else:
                    self.assertTrue(result["ok"])
                    self.assertEqual(result["final_content"].strip(), "Complete.")
                    self.assertEqual(client.chat_stream.call_count, 5)
                    self.assertEqual(client._progressive_trim.call_count, 2)

    def test_agent_loop_backoff_keeps_three_retry_limit(self):
        client = self._loop_client([
            [{"type": "error", "error": "HTTP 503 service unavailable"}]
            for _ in range(4)
        ])
        client._progressive_trim = mock.Mock(
            side_effect=lambda messages, *args, **kwargs: messages
        )

        result = client.agent_loop_stream(
            messages=[{"role": "user", "content": "inspect"}],
            model="test-model",
            provider="test-provider",
            tools_override=[],
        )

        self.assertFalse(result["ok"])
        self.assertFalse(result.get("stopped", False))
        self.assertEqual(client.chat_stream.call_count, 4)
        self.assertEqual(client._stop_event.wait.call_args_list, [
            mock.call(5), mock.call(10), mock.call(15),
        ])
        client._get_streaming_tool_executor.return_value.execute_round.assert_not_called()

    def test_tool_call_limit_stops_before_executing_and_pairs_every_call(self):
        client = self._loop_client([
            [self._tool_call_chunk("a"), self._tool_call_chunk("b"), {"type": "done", "usage": {}}],
        ])
        streamed = []

        result = client.agent_loop_stream(
            messages=[{"role": "user", "content": "go"}],
            model="test-model",
            provider="test-provider",
            tools_override=[],
            on_content=streamed.append,
            max_tool_calls=1,
        )

        client._get_streaming_tool_executor.return_value.execute_round.assert_not_called()
        self.assertEqual(result["stop_reason"], "max_tool_calls")
        tool_msgs = [m for m in result["new_messages"] if m.get("role") == "tool"]
        self.assertEqual({m["tool_call_id"] for m in tool_msgs}, {"a", "b"})
        self.assertTrue(all("未执行" in m["content"] for m in tool_msgs))
        self.assertTrue(any("继续" in s for s in streamed))

    def test_max_iterations_reports_visible_stop_reason(self):
        tool_round = [self._tool_call_chunk("a"), {"type": "done", "usage": {}}]
        summary = [{"type": "content", "content": "summary"}, {"type": "done", "usage": {}}]
        client = self._loop_client([tool_round, tool_round, summary])
        streamed = []

        result = client.agent_loop_stream(
            messages=[{"role": "user", "content": "go"}],
            model="test-model",
            provider="test-provider",
            tools_override=[],
            on_content=streamed.append,
            max_iterations=2,
        )

        self.assertEqual(result["stop_reason"], "max_iterations")
        self.assertIn("继续", result["final_content"])
        self.assertTrue(any("继续" in s for s in streamed))

    def test_agent_loop_summary_preserves_user_thinking_setting(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                client = self._loop_client([
                    [self._tool_call_chunk("a"), {"type": "done", "usage": {}}],
                    [{"type": "content", "content": "Summary."}, {"type": "done", "usage": {}}],
                ])

                result = client.agent_loop_stream(
                    messages=[{"role": "user", "content": "inspect"}],
                    model="test-model",
                    provider="test-provider",
                    tools_override=[],
                    enable_thinking=enabled,
                    max_iterations=1,
                )

                self.assertTrue(result["ok"])
                self.assertEqual(result["stop_reason"], "max_iterations")
                self.assertEqual(client.chat_stream.call_count, 2)
                summary_request = client.chat_stream.call_args.kwargs
                self.assertIs(summary_request.get("enable_thinking"), enabled)
                self.assertIsNone(summary_request["tools"])
                self.assertIsNone(summary_request["tool_choice"])
                self.assertEqual(summary_request["max_tokens"], 500)

    def test_agent_loop_summary_cancellation_preserves_work_without_limit_notice(self):
        modes = ("before", "before_without_summary", "stopped", "event_done", "event_empty", "content_callback")
        for mode in modes:
            with self.subTest(mode=mode):
                def summary_stream():
                    yield {"type": "content", "content": "Partial summary."}
                    if mode == "stopped":
                        yield {"type": "stopped"}
                    elif mode == "content_callback":
                        yield {"type": "content", "content": "Unexpected."}
                    else:
                        client.request_stop()
                        if mode == "event_done":
                            yield {"type": "done", "usage": {}}

                tool_round = [self._tool_call_chunk("a"), {"type": "done", "usage": {
                    "prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
                }}]
                if mode == "before_without_summary":
                    tool_round.insert(0, {"type": "content", "content": "Working."})
                client = self._loop_client([tool_round, summary_stream()])
                client._stop_event = threading.Event()
                streamed = []

                def on_content(content):
                    streamed.append(content)
                    if mode == "content_callback":
                        client.request_stop()

                result = client.agent_loop_stream(
                    messages=[{"role": "user", "content": "inspect"}],
                    model="test-model",
                    provider="test-provider",
                    tools_override=[],
                    on_content=on_content,
                    on_tool_result=(
                        lambda *args: client.request_stop()
                    ) if mode.startswith("before") else None,
                    max_iterations=1,
                )

                self.assertFalse(result["ok"])
                self.assertTrue(result["stopped"])
                self.assertNotIn("stop_reason", result)
                if mode.startswith("before"):
                    expected_content = "Working." if mode == "before_without_summary" else ""
                    self.assertEqual(client.chat_stream.call_count, 1)
                    self.assertEqual(result["final_content"], "")
                else:
                    expected_content = "Partial summary."
                    self.assertEqual(client.chat_stream.call_count, 2)
                    self.assertEqual(result["final_content"], expected_content)
                self.assertEqual(result["content"], expected_content)
                self.assertEqual("".join(streamed), expected_content)
                self.assertEqual(result["iterations"], 1)
                self.assertEqual(result["usage"]["total_tokens"], 18)
                self.assertEqual(len(result["tool_calls_history"]), 1)
                tool_messages = [message for message in result["new_messages"] if message["role"] == "tool"]
                self.assertEqual([message["tool_call_id"] for message in tool_messages], ["a"])

    def test_near_iteration_limit_injects_wrap_up_hint_once(self):
        tool_round = [self._tool_call_chunk("a"), {"type": "done", "usage": {}}]
        summary = [{"type": "content", "content": "summary"}, {"type": "done", "usage": {}}]
        client = self._loop_client([tool_round, tool_round, tool_round, summary])

        result = client.agent_loop_stream(
            messages=[{"role": "user", "content": "go"}],
            model="test-model",
            provider="test-provider",
            tools_override=[],
            enable_thinking=False,
            max_iterations=3,
        )

        tool_msgs = [m for m in result["new_messages"] if m.get("role") == "tool"]
        hinted = [m for m in tool_msgs if "上限" in m["content"]]
        self.assertEqual(len(hinted), 1)

    def test_loop_abort_keeps_real_results_of_already_executed_calls(self):
        client = self._loop_client([
            [self._tool_call_chunk("a"), self._tool_call_chunk("b"), {"type": "done", "usage": {}}],
        ])
        client._get_streaming_tool_executor.return_value.execute_round.return_value = {
            "results_ordered": [
                {"success": True, "result": "RESULT_A"},
                {"success": True, "result": "RESULT_B"},
            ],
            "dedup_flags": [False, False],
            "early_skip_count": 0,
        }
        client._tool_loop_abort_reason = mock.Mock(return_value="loop detected")

        result = client.agent_loop_stream(
            messages=[{"role": "user", "content": "go"}],
            model="test-model",
            provider="test-provider",
            tools_override=[],
        )

        tool_msgs = {m["tool_call_id"]: m["content"] for m in result["new_messages"] if m.get("role") == "tool"}
        self.assertIn("RESULT_A", tool_msgs.get("a", ""))
        self.assertIn("RESULT_B", tool_msgs.get("b", ""))
        self.assertEqual(len(result["tool_calls_history"]), 2)

    def test_lexical_embedder_does_not_probe_semantic_model(self):
        with mock.patch.object(LocalEmbedder, "_try_load_model") as try_load:
            embedder = LocalEmbedder(load_semantic_model=False)

        try_load.assert_not_called()
        self.assertEqual(embedder._backend, "fallback")

    def test_gpt5_models_use_default_temperature(self):
        self.assertTrue(AIClient.requires_temperature_one("gpt-5.6"))
        self.assertTrue(AIClient.requires_temperature_one("gpt-5.3-codex"))
        self.assertEqual(AIClient._payload_temperature("gpt-5.6", 0.17), 1)

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

    def test_archived_tool_result_can_be_read_from_model_visible_reference(self):
        client = object.__new__(AIClient)
        with tempfile.TemporaryDirectory() as directory:
            store = ToolResultStore(Path(directory), "archive-replay", threshold=20)
            archived = store.archive_if_large(
                "get_scene_snapshot",
                {"success": True, "result": {"nodes": ["/obj/geo1/OUT"]}},
            )

            visible = AIClient._compress_tool_result(client, "get_scene_snapshot", archived)

            self.assertIn(archived["result_ref"], visible)
            reference = json.loads(visible)
            page = store.read(reference["result_ref"], pointer="/result/nodes", limit=100)
            visible_page = AIClient._compress_tool_result(client, "read_tool_result", page)
            self.assertIn("/obj/geo1/OUT", visible_page)
            self.assertEqual(json.loads(visible_page)["next_offset"], None)

    def test_archived_failure_keeps_status_and_all_error_pages(self):
        client = object.__new__(AIClient)
        error = "cook failed: " + "missing cache " * 20
        with tempfile.TemporaryDirectory() as directory:
            store = ToolResultStore(Path(directory), "failed-archive", threshold=20)
            archived = store.archive_if_large("inspect_node", {"success": False, "error": error})
            visible = json.loads(AIClient._compress_tool_result(client, "inspect_node", archived))
            self.assertFalse(visible["success"])
            offset = 0
            pages = []
            while offset is not None:
                page = store.read(visible["result_ref"], pointer="/error", offset=offset, limit=23)
                rendered = json.loads(AIClient._compress_tool_result(client, "read_tool_result", page))
                self.assertEqual(rendered["pointer"], "/error")
                self.assertEqual(rendered["offset"], offset)
                pages.append(rendered["content"])
                offset = rendered["next_offset"]
                if offset is not None:
                    self.assertGreater(offset, rendered["offset"])
            self.assertGreater(len(pages), 1)
            self.assertEqual(json.loads("".join(pages)), error)

    def test_archived_page_redacts_secrets_before_llm(self):
        client = object.__new__(AIClient)
        rendered = AIClient._compress_tool_result(client, "read_tool_result", {
            "success": True, "result_ref": "res_" + "a" * 32,
            "content": "token=abc123456789\nsecret=sk-testsecret1234567890",
            "offset": 0, "next_offset": None,
        })
        self.assertIn("[REDACTED]", rendered)
        self.assertNotIn("abc123456789", rendered)
        self.assertNotIn("sk-testsecret", rendered)

    def test_agent_loop_replays_real_archive_and_page_results(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ToolResultStore(Path(directory), "loop-replay", threshold=20)
            archived = store.archive_if_large(
                "get_scene_snapshot", {"success": True, "result": "missing cache, annotation only"},
            )
            page = store.read(archived["result_ref"], pointer="/result", limit=100)
            client = self._loop_client([
                [self._tool_call_chunk("archive", "get_scene_snapshot"), {"type": "done", "usage": {}}],
                [{"type": "tool_call", "tool_call": {
                    "id": "read", "type": "function", "function": {
                        "name": "read_tool_result", "arguments": json.dumps({
                            "result_ref": archived["result_ref"], "pointer": "/result",
                        }),
                    },
                }}, {"type": "done", "usage": {}}],
                [{"type": "content", "content": "Annotation complete; cache still missing."},
                 {"type": "done", "usage": {}}],
            ])
            executor = client._get_streaming_tool_executor.return_value
            executor.execute_round.side_effect = [
                {"results_ordered": [payload], "dedup_flags": [False], "early_skip_count": 0}
                for payload in (archived, page)
            ]

            result = client.agent_loop_stream(
                messages=[{"role": "user", "content": "Inspect missing cache; annotation only."}],
                model="test-model", provider="test-provider",
                tools_override=[{"type": "function", "function": {"name": name}}
                                for name in ("get_scene_snapshot", "read_tool_result")],
            )

            self.assertTrue(result["ok"])
            tools = [message for message in result["new_messages"] if message["role"] == "tool"]
            self.assertEqual([message["tool_call_id"] for message in tools], ["archive", "read"])
            self.assertIn(archived["result_ref"], tools[0]["content"])
            self.assertIn("missing cache, annotation only", tools[1]["content"])
            self.assertEqual(executor.execute_round.call_count, 2)

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

    def test_tool_result_compression_preserves_validation_contract_signals(self):
        client = object.__new__(AIClient)
        compressed = AIClient._compress_tool_result(
            client,
            "temporary_auto_validate_geometry",
            {
                "success": True,
                "result": "x" * 1000,
                "health": "unknown",
                "freshness": {"status": "fresh", "cook_succeeded": True},
                "validation_blocked": True,
                "recovery_hint": "retry target validation",
                "restore_attempted": True,
                "restore_succeeded": False,
                "restored_update_mode": "AutoUpdate",
            },
        )

        self.assertIn("health=unknown", compressed)
        self.assertIn("freshness=fresh", compressed)
        self.assertIn("validation_blocked=true", compressed)
        self.assertIn("restore_succeeded=false", compressed)
        self.assertIn("retry target validation", compressed)

    def test_failed_tool_result_compression_preserves_validation_contract_signals(self):
        client = object.__new__(AIClient)
        compressed = AIClient._compress_tool_result(
            client,
            "temporary_auto_validate_geometry",
            {
                "success": False,
                "error": "恢复 Update Mode 失败",
                "health": "unknown",
                "freshness": {"status": "unknown"},
                "restore_attempted": True,
                "restore_succeeded": False,
                "restored_update_mode": "unknown",
            },
        )

        self.assertIn("恢复 Update Mode 失败", compressed)
        self.assertIn("health=unknown", compressed)
        self.assertIn("freshness=unknown", compressed)
        self.assertIn("restore_succeeded=false", compressed)

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

    def test_list_skills_parameter_churn_has_hard_discovery_budget(self):
        reason = AIClient._tool_loop_abort_reason(
            tool_name="list_skills",
            consecutive_same_calls=1,
            window_same_count=1,
            consecutive_same_tool=8,
        )

        self.assertIn("list_skills", reason)
        self.assertIn("run_skill", reason)

    def test_batch_mutation_is_not_stopped_by_discovery_budget(self):
        reason = AIClient._tool_loop_abort_reason(
            tool_name="set_node_parameter",
            consecutive_same_calls=1,
            window_same_count=1,
            consecutive_same_tool=8,
        )

        self.assertIsNone(reason)


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
        client._progressive_trim = mock.Mock(side_effect=lambda messages, history, **kwargs: [
            {"role": "user", "content": "inspect"}
        ])
        client.chat_stream = mock.Mock(side_effect=[
            iter([{"type": "error", "error": "HTTP 413 payload too large"}]),
            iter([{"type": "content", "content": "done"}, {"type": "done", "usage": {}}]),
        ])
        tools = [{"type": "function", "function": {"name": "inspect_node"}}]
        content_updates = []

        result = client.agent_loop_stream(
            messages=[
                {"role": "user", "content": "old context"},
                {"role": "assistant", "content": "old answer"},
                {"role": "user", "content": "inspect"},
            ],
            model="test-model",
            provider="test-provider",
            tools_override=tools,
            on_content=content_updates.append,
            max_iterations=2,
            context_limit=10000,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(client.chat_stream.call_count, 2)
        self.assertIs(client._progressive_trim.call_args.kwargs["tools"], tools)
        self.assertEqual(client._progressive_trim.call_args.kwargs["trim_level"], 1)
        self.assertTrue(any("请求体过大" in update for update in content_updates))
        self.assertFalse(any("上下文超限" in update for update in content_updates))

    def test_request_body_budget_removes_old_images_before_current_image(self):
        old_image = "data:image/png;base64," + ("A" * 2500)
        current_image = "data:image/png;base64," + ("B" * 2500)
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "old"},
                {"type": "image_url", "image_url": {"url": old_image}},
            ]},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": [
                {"type": "text", "text": "current"},
                {"type": "image_url", "image_url": {"url": current_image}},
            ]},
        ]

        result, removed = AIClient._fit_messages_to_request_body_budget(
            messages, tools=[], max_body_bytes=3500
        )

        self.assertEqual(removed, 1)
        self.assertIsInstance(result[0]["content"], str)
        self.assertEqual(result[-1]["content"][1]["image_url"]["url"], current_image)

    def test_request_body_budget_fails_closed_when_current_image_cannot_fit(self):
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "current"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + ("A" * 5000)}},
        ]}]

        with self.assertRaisesRegex(ValueError, "请求体仍超过"):
            AIClient._fit_messages_to_request_body_budget(
                messages, tools=[], max_body_bytes=1000
            )

    def test_agent_loop_http_413_aborts_when_request_body_did_not_shrink(self):
        client = object.__new__(AIClient)
        client._tool_executor = mock.Mock()
        client._stop_event = mock.Mock()
        client._stop_event.is_set.return_value = False
        client._get_streaming_tool_executor = mock.Mock()
        client._get_streaming_tool_executor.return_value.reset.return_value = None
        client._sanitize_working_messages = lambda messages: messages
        client._ensure_context_within_budget = lambda messages, tools, limit: None
        client._progressive_trim = mock.Mock(side_effect=lambda messages, history, **kwargs: list(messages))
        client.chat_stream = mock.Mock(return_value=iter([
            {"type": "error", "error": "HTTP 413 Request Entity Too Large"},
        ]))

        result = client.agent_loop_stream(
            messages=[{"role": "user", "content": "inspect"}],
            model="test-model",
            provider="test-provider",
            tools_override=[],
            max_iterations=4,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(client.chat_stream.call_count, 1)
        self.assertIn("请求体过大", result["error"])

    def test_json_mode_http_413_aborts_without_context_overflow_message(self):
        client = object.__new__(AIClient)
        client._tool_executor = mock.Mock()
        client._stop_event = mock.Mock()
        client._stop_event.is_set.return_value = False
        client._sanitize_working_messages = lambda messages: messages
        client._ensure_context_within_budget = lambda messages, tools, limit: None
        client._progressive_trim = mock.Mock(side_effect=lambda messages, history, **kwargs: list(messages))
        client.chat_stream = mock.Mock(return_value=iter([
            {"type": "error", "error": "HTTP 413 Request Entity Too Large"},
        ]))
        content_updates = []

        result = client.agent_loop_json_mode(
            messages=[{"role": "user", "content": "inspect"}],
            model="test-model",
            provider="test-provider",
            tools_override=[],
            on_content=content_updates.append,
            max_iterations=4,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(client.chat_stream.call_count, 1)
        self.assertIn("请求体过大", result["error"])
        self.assertFalse(any("上下文超限" in update for update in content_updates))


if __name__ == "__main__":
    unittest.main()