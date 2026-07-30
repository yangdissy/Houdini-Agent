# -*- coding: utf-8 -*-
"""Provider adapter tests."""

import unittest

from houdini_agent.utils.provider_adapters import AnthropicRequestAdapter, AnthropicStreamEventParser


def _adapter():
    return AnthropicRequestAdapter(lambda model: model == "k3")


class AnthropicRequestAdapterTest(unittest.TestCase):
    def test_converts_system_user_assistant_and_tool_messages(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "working",
                "tool_calls": [{
                    "id": "toolu_1",
                    "function": {"name": "inspect_node", "arguments": '{"node_path":"/obj/geo1"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "toolu_1", "content": "ok"},
        ]

        system_text, anth_messages = _adapter().convert_messages(messages)

        self.assertEqual(system_text, "sys")
        self.assertEqual(anth_messages[0], {"role": "user", "content": "hello"})
        assistant_blocks = anth_messages[1]["content"]
        self.assertEqual(assistant_blocks[0], {"type": "text", "text": "working"})
        self.assertEqual(assistant_blocks[1]["type"], "tool_use")
        self.assertEqual(assistant_blocks[1]["input"], {"node_path": "/obj/geo1"})
        self.assertEqual(anth_messages[2]["content"][0]["type"], "tool_result")

    def test_build_stream_payload_maps_temperature_thinking_and_tool_choice(self):
        payload = _adapter().build_payload(
            messages=[{"role": "user", "content": "hi"}],
            model="claude-test",
            provider="duojie",
            temperature=2.0,
            max_tokens=12000,
            tools=[{"function": {"name": "web_search", "description": "search", "parameters": {"type": "object"}}}],
            tool_choice="required",
            enable_thinking=True,
            stream=True,
        )

        self.assertTrue(payload["stream"])
        self.assertEqual(payload["temperature"], 1.0)
        self.assertEqual(payload["thinking"], {"type": "enabled", "budget_tokens": 10000})
        self.assertEqual(payload["tool_choice"], {"type": "any"})
        self.assertEqual(payload["tools"][0]["input_schema"], {"type": "object"})

    def test_kimi_coding_only_enables_thinking_for_kimi_for_coding(self):
        k3_payload = _adapter().build_payload(
            messages=[{"role": "user", "content": "hi"}],
            model="k3",
            provider="kimi_coding",
            temperature=0.2,
            max_tokens=4096,
            tools=None,
            tool_choice="auto",
            enable_thinking=True,
            stream=True,
        )
        coding_payload = _adapter().build_payload(
            messages=[{"role": "user", "content": "hi"}],
            model="kimi-for-coding",
            provider="kimi_coding",
            temperature=0.2,
            max_tokens=4096,
            tools=None,
            tool_choice="auto",
            enable_thinking=True,
            stream=True,
        )

        self.assertEqual(k3_payload["temperature"], 1)
        self.assertNotIn("thinking", k3_payload)
        self.assertEqual(coding_payload["thinking"], {"type": "enabled", "budget_tokens": 4096})

    def test_headers_include_stream_accept_and_kimi_user_agent(self):
        headers = _adapter().build_headers(api_key="key", provider="kimi_coding", stream=True)

        self.assertEqual(headers["x-api-key"], "key")
        self.assertEqual(headers["Accept"], "text/event-stream")
        self.assertEqual(headers["User-Agent"], "claude-code/0.1.0")

    def test_normalize_response_maps_text_tools_stop_reason_and_usage(self):
        response = {
            "content": [
                {"type": "text", "text": "done"},
                {"type": "tool_use", "id": "toolu_1", "name": "inspect_node", "input": {"node_path": "/obj/geo1"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 2, "output_tokens": 3},
        }

        normalized = _adapter().normalize_response(response, _parse_usage)

        self.assertTrue(normalized["ok"])
        self.assertEqual(normalized["content"], "done")
        self.assertEqual(normalized["finish_reason"], "tool_calls")
        self.assertEqual(normalized["usage"]["total_tokens"], 5)
        self.assertEqual(normalized["tool_calls"][0]["function"]["name"], "inspect_node")
        self.assertEqual(normalized["tool_calls"][0]["function"]["arguments"], '{"node_path": "/obj/geo1"}')
        self.assertIs(normalized["raw"], response)

    def test_normalize_response_empty_content_and_end_turn(self):
        normalized = _adapter().normalize_response({"content": [], "stop_reason": "end_turn"}, _parse_usage)

        self.assertIsNone(normalized["content"])
        self.assertIsNone(normalized["tool_calls"])
        self.assertEqual(normalized["finish_reason"], "stop")


def _parse_usage(usage):
    prompt = usage.get("input_tokens", 0)
    completion = usage.get("output_tokens", 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cache_hit_tokens": 0,
        "cache_miss_tokens": 0,
        "cache_hit_rate": 0,
    }


class AnthropicStreamEventParserTest(unittest.TestCase):
    def test_text_thinking_tool_call_and_done_chunks(self):
        parser = AnthropicStreamEventParser(_parse_usage, enable_thinking=True)

        self.assertEqual(
            parser.process_event("message_start", '{"type":"message_start","message":{"usage":{"input_tokens":3}}}'),
            [],
        )
        self.assertEqual(
            parser.process_event("content_block_delta", '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hello"}}'),
            [{"type": "content", "content": "hello"}],
        )
        self.assertEqual(
            parser.process_event("content_block_delta", '{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"hmm"}}'),
            [{"type": "thinking", "content": "hmm"}],
        )
        parser.process_event(
            "content_block_start",
            '{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_1","name":"inspect_node"}}',
        )
        self.assertEqual(
            parser.process_event("content_block_delta", '{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\\"node_path\\\":"}}'),
            [{"type": "tool_args_delta", "index": 1, "name": "inspect_node", "delta": '{"node_path":', "accumulated": '{"node_path":'}],
        )
        parser.process_event("content_block_delta", '{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"\\\"/obj/geo1\\\"}"}}')
        tool_call = parser.process_event("content_block_stop", '{"type":"content_block_stop","index":1}')[0]
        self.assertEqual(tool_call["type"], "tool_call")
        self.assertEqual(tool_call["tool_call"]["function"]["name"], "inspect_node")
        self.assertEqual(tool_call["tool_call"]["function"]["arguments"], '{"node_path":"/obj/geo1"}')

        parser.process_event(
            "message_delta",
            '{"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":5}}',
        )
        done = parser.process_event("message_stop", '{"type":"message_stop"}')[0]
        self.assertEqual(done["finish_reason"], "tool_calls")
        self.assertEqual(done["usage"]["prompt_tokens"], 3)
        self.assertEqual(done["usage"]["completion_tokens"], 5)

    def test_thinking_can_be_suppressed(self):
        parser = AnthropicStreamEventParser(_parse_usage, enable_thinking=False)

        chunks = parser.process_event(
            "content_block_delta",
            '{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"hidden"}}',
        )

        self.assertEqual(chunks, [])

    def test_invalid_json_event_is_ignored(self):
        parser = AnthropicStreamEventParser(_parse_usage, enable_thinking=True)

        self.assertEqual(parser.process_event("message_start", "not json"), [])


if __name__ == "__main__":
    unittest.main()
