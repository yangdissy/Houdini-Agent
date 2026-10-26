# -*- coding: utf-8 -*-

import unittest
import json
from unittest import mock

from houdini_agent.core.agent_request_assembly import (
    build_context,
    finalize_context_request,
    finalize_tools,
    has_prior_completed_turn,
    normalize_history,
    normalize_provider_messages,
    prepare_history_for_request,
)


def _image(text, url):
    return [
        {'type': 'text', 'text': text},
        {'type': 'image_url', 'image_url': {'url': url}},
    ]


class AgentRequestAssemblyTest(unittest.TestCase):
    def test_natural_language_discovery_ranks_names_and_intent(self):
        from houdini_agent.core.agent_request_assembly import ToolExposureState
        from houdini_agent.utils.tool_registry import ToolRegistry

        registry = ToolRegistry()
        schemas = [{"type": "function", "function": {"name": name, "description": description, "parameters": {}}}
                   for name, description in (
                       ("search_tool_contracts", "search tools"),
                       ("get_usd_prim_info", "Inspect USD prim details"),
                       ("get_usd_layer_stack", "Inspect USD layers"),
                   )]
        registry.register_core_tools(schemas)
        exposure = ToolExposureState(registry, schemas[:1])

        result = exposure.load("USD prim details", limit=1)

        self.assertTrue(result["success"])
        self.assertEqual(result["result"]["matches"][0]["name"], "get_usd_prim_info")
        chinese = exposure.load("查看 USD 场景", limit=2)
        self.assertTrue(chinese["success"])

    def test_tool_discovery_budget_failure_does_not_partially_load_tools(self):
        from houdini_agent.core.agent_request_assembly import ToolExposureState
        from houdini_agent.utils.tool_registry import ToolRegistry

        registry = ToolRegistry()
        small = {"type": "function", "function": {"name": "search_tool_contracts", "description": "search", "parameters": {}}}
        large = {"type": "function", "function": {"name": "get_usd_prim_info", "description": "large " * 3000, "parameters": {}}}
        registry.register_core_tools([small, large])
        exposure = ToolExposureState(registry, [small], max_schema_tokens=200)
        before = exposure.snapshot()

        result = exposure.load("get_usd_prim_info")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "tool_schema_budget")
        self.assertEqual(exposure.snapshot(), before)

    def test_tool_discovery_loads_only_current_run_and_current_permissions(self):
        from houdini_agent.core.agent_request_assembly import ToolExposureState
        from houdini_agent.utils.tool_registry import ToolRegistry

        registry = ToolRegistry()
        schemas = [{"type": "function", "function": {
            "name": name, "description": name, "parameters": {},
        }} for name in ("get_network_structure", "get_usd_prim_info", "execute_python", "web_search")]
        registry.register_core_tools(schemas)
        first = ToolExposureState(registry, schemas[:1], mode="ask", use_web=False)
        other = ToolExposureState(registry, schemas[:1], mode="ask", use_web=False)

        result = first.load("get_usd_prim_info")

        self.assertTrue(result["success"])
        self.assertIn("get_usd_prim_info", {tool["function"]["name"] for tool in first.snapshot()})
        self.assertNotIn("get_usd_prim_info", {tool["function"]["name"] for tool in other.snapshot()})
        self.assertFalse(first.load("execute_python")["success"])
        self.assertFalse(first.load("web_search")["success"])
        registry.set_enabled("get_usd_prim_info", False)
        self.assertNotIn("get_usd_prim_info", {tool["function"]["name"] for tool in first.snapshot()})

    def test_first_user_message_does_not_count_as_prior_completed_turn(self):
        self.assertFalse(has_prior_completed_turn([
            {'role': 'system', 'content': 'scene snapshot'},
            {'role': 'user', 'content': 'build a box'},
        ]))

    def test_assistant_response_counts_as_prior_completed_turn(self):
        self.assertTrue(has_prior_completed_turn([
            {'role': 'user', 'content': 'first'},
            {'role': 'assistant', 'content': 'done'},
            {'role': 'user', 'content': 'second'},
        ]))

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

    def test_request_history_compacts_old_tool_results_without_mutating_history(self):
        history = []
        for index in range(4):
            history.extend([
                {'role': 'user', 'content': 'request %d' % index},
                {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'call_%d' % index,
                    'function': {'name': 'inspect_node', 'arguments': '{}'},
                }]},
                {'role': 'tool', 'tool_call_id': 'call_%d' % index, 'content': str(index) * 250},
            ])

        result = prepare_history_for_request(
            history,
            supports_vision=False,
            fix_alternation=lambda messages: messages,
            tool_result_text=lambda name, content: '%s=%s' % (name, content),
            image_placeholder='image removed',
            summarize_tool_content=lambda content, limit: content[:limit] + '...[summary]',
            protect_recent_rounds=3,
        )

        tool_results = [message['content'] for message in result if message['role'] == 'tool']
        self.assertTrue(tool_results[0].endswith('...[summary]'))
        self.assertEqual(tool_results[1:], [str(index) * 250 for index in range(1, 4)])
        self.assertEqual(history[2]['content'], '0' * 250)

    def test_old_tool_protocol_and_unknown_validation_survive_request_assembly(self):
        with mock.patch.dict('sys.modules', {'requests': mock.Mock()}):
            from houdini_agent.utils.ai_client import AIClient

        client = object.__new__(AIClient)
        reference = 'res_' + 'a' * 32
        payloads = [
            ('get_scene_snapshot', {
                'success': False, 'stored': True, 'result_ref': reference,
                'size': 20000, 'result': 'Large tool result archived. ' * 20,
            }),
            ('read_tool_result', {
                'success': True, 'result_ref': reference, 'pointer': '/result/nodes',
                'offset': 0, 'next_offset': 600, 'total_chars': 1200,
                'content': 'cached geometry /obj/geo1/OUT ' * 30,
            }),
            ('temporary_auto_validate_geometry', {
                'success': False, 'error': 'restore failed /obj/geo1/OUT ' * 30,
                'health': 'unknown', 'freshness': {'status': 'stale'},
                'validation_blocked': True, 'restore_succeeded': False,
            }),
        ]
        history = []
        for index, (tool_name, payload) in enumerate(payloads):
            history.extend([
                {'role': 'user', 'content': 'request %d' % index},
                {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'protocol_%d' % index,
                    'function': {'name': tool_name, 'arguments': '{}'},
                }]},
                {'role': 'tool', 'tool_call_id': 'protocol_%d' % index,
                 'content': AIClient._compress_tool_result(client, tool_name, payload)},
            ])

        prepared = prepare_history_for_request(
            history, supports_vision=False,
            fix_alternation=lambda messages: messages,
            tool_result_text=lambda name, content: '%s=%s' % (name, content),
            image_placeholder='image removed',
            summarize_tool_content=AIClient._summarize_tool_content,
            protect_recent_rounds=0,
        )
        outgoing = normalize_provider_messages(prepared, is_reasoning_model=False)
        results = [message for message in outgoing if message['role'] == 'tool']
        archived = json.loads(results[0]['content'])
        self.assertEqual(archived['result_ref'], reference)
        self.assertFalse(archived['success'])
        page = json.loads(results[1]['content'])
        self.assertEqual(page['result_ref'], reference)
        self.assertEqual(page['pointer'], '/result/nodes')
        self.assertEqual(page['offset'], 0)
        self.assertEqual(page['next_offset'], 600)
        self.assertTrue(page['content_omitted'])
        self.assertNotIn('content', page)
        self.assertLess(len(results[1]['content']), len(history[5]['content']))
        repeated_page = json.loads(AIClient._summarize_tool_content(results[1]['content']))
        self.assertEqual(repeated_page, page)
        self.assertIn('health=unknown', results[2]['content'])
        self.assertIn('freshness=stale', results[2]['content'])
        self.assertIn('validation_blocked=true', results[2]['content'])
        self.assertIn('restore_succeeded=false', results[2]['content'])
        self.assertEqual([message['tool_call_id'] for message in results],
                         ['protocol_0', 'protocol_1', 'protocol_2'])

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

    def test_selected_tools_are_not_expanded_without_registry_supplements(self):
        selected = {
            'type': 'function',
            'function': {'name': 'create_node', 'description': 'create'},
        }
        tools = finalize_tools([selected], [], supports_vision=True)
        self.assertEqual(tools, [selected])

    def test_registry_supplement_is_added_without_duplicates(self):
        selected = {
            'type': 'function',
            'function': {'name': 'create_node', 'description': 'create'},
        }
        plugin = {
            'type': 'function',
            'function': {'name': 'plugin_tool', 'description': 'plugin'},
        }
        tools = finalize_tools([selected], [selected, plugin], supports_vision=True)
        self.assertEqual(
            [tool['function']['name'] for tool in tools],
            ['create_node', 'plugin_tool'],
        )

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