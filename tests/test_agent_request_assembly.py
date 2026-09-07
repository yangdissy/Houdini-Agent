# -*- coding: utf-8 -*-

import unittest

from houdini_agent.core.agent_request_assembly import (
    build_context,
    finalize_context_request,
    finalize_tools,
    normalize_history,
    normalize_provider_messages,
)


def _image(text, url):
    return [
        {'type': 'text', 'text': text},
        {'type': 'image_url', 'image_url': {'url': url}},
    ]


class AgentRequestAssemblyTest(unittest.TestCase):
    def test_history_strips_old_image_and_keeps_current_vision_image(self):
        current = _image('current', 'current-image')
        result = normalize_history(
            [
                {'role': 'user', 'content': _image('old', 'old-image')},
                {'role': 'assistant', 'content': 'answer'},
                {'role': 'user', 'content': current},
            ],
            supports_vision=True,
            fix_alternation=lambda messages: messages,
            tool_result_text=lambda name, content: '%s: %s' % (name, content),
            image_placeholder='image removed',
        )
        self.assertEqual(result[0]['content'], 'old')
        self.assertIs(result[-1]['content'], current)

    def test_history_converts_malformed_legacy_tool_result(self):
        result = normalize_history(
            [{'role': 'tool', 'name': 'legacy', 'content': 'x' * 600}],
            supports_vision=False,
            fix_alternation=lambda messages: messages,
            tool_result_text=lambda name, content: '%s=%s' % (name, content),
            image_placeholder='image removed',
        )
        self.assertEqual(result[0]['role'], 'assistant')
        self.assertTrue(result[0]['content'].startswith('legacy='))
        self.assertEqual(len(result[0]['content']), len('legacy=' ) + 500)

    def test_reasoning_assistant_normalization_preserves_tool_call_none(self):
        result = normalize_provider_messages([{
            'role': 'assistant',
            'content': '<think>private</think>',
            'tool_calls': [{'id': 'call_1'}],
            'ignored': 'internal',
        }], is_reasoning_model=True)
        self.assertEqual(result, [{
            'role': 'assistant',
            'content': None,
            'reasoning_content': '',
            'tool_calls': [{'id': 'call_1'}],
        }])

    def test_capture_viewport_degrades_without_mutating_registry_schema(self):
        viewport = {
            'type': 'function',
            'function': {'name': 'capture_viewport', 'description': 'original'},
        }
        tools = finalize_tools([], [viewport], supports_vision=False)
        self.assertEqual(viewport['function']['description'], 'original')
        self.assertIn('必须指定 output_path', tools[0]['function']['description'])

    def test_visual_review_is_removed_for_non_vision_models(self):
        visual_review = {
            'type': 'function',
            'function': {'name': 'visual_review', 'description': 'review'},
        }
        tools = finalize_tools([], [visual_review], supports_vision=False)
        self.assertEqual(tools, [])

    def test_final_messages_stay_normalized_after_pruning(self):
        assistant_call = {
            'role': 'assistant',
            'content': None,
            'tool_calls': [{'id': 'call_1', 'function': {'name': 'x', 'arguments': '{}'}}],
            'thinking': 'internal',
            'unexpected': 'remove me',
        }
        assembly = build_context(
            prefix_messages=[{'role': 'system', 'content': 'rules', 'unexpected': 'remove me'}],
            history_messages=[
                {'role': 'user', 'content': 'old'},
                assistant_call,
                {'role': 'tool', 'tool_call_id': 'call_1', 'content': 'result'},
                {'role': 'user', 'content': 'current'},
            ],
            dynamic_sections=[],
        )
        result = finalize_context_request(
            assembly,
            selected_tools=[],
            registry_tools=[],
            supports_vision=True,
            is_reasoning_model=True,
            context_limit=100,
            count_tokens=lambda messages, tools: len(messages),
            summarize_tool_content=None,
        )
        self.assertTrue(result.budget_result.within_budget)
        self.assertTrue(all('unexpected' not in message for message in result.messages))
        normalized_call = next(message for message in result.messages if message.get('tool_calls'))
        normalized_result = next(message for message in result.messages if message.get('role') == 'tool')
        self.assertEqual(normalized_call['tool_calls'][0]['id'], normalized_result['tool_call_id'])
        self.assertIsNone(normalized_call['content'])
        self.assertEqual(normalized_call['reasoning_content'], '')


if __name__ == '__main__':
    unittest.main()