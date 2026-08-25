# -*- coding: utf-8 -*-
"""token_optimizer 单元测试（不依赖 Houdini hou，也不依赖 tiktoken）。"""

import unittest

from houdini_agent.utils.token_optimizer import (
    count_tokens,
    calculate_cost,
    calculate_cost_from_stats,
    _match_pricing,
    _DEFAULT_PRICING,
    MODEL_PRICING,
    TokenOptimizer,
    TokenBudget,
    TokenEstimate,
    CompressionStats,
    CompressionStrategy,
    plan_context_rounds,
    compress_old_round_tool_results,
    flatten_context_rounds,
    prune_context_rounds_to_token_target,
    assemble_context_messages,
    DynamicContextSection,
    build_context_assembly,
    prune_context_assembly_to_token_target,
)


class CountTokensTest(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(count_tokens(""), 0)

    def test_non_empty_at_least_one(self):
        self.assertGreaterEqual(count_tokens("hi"), 1)

    def test_chinese_counts(self):
        # 启发式：中文字符按 1/1.5 计，长字符串应有合理 token 数
        n = count_tokens("这是一段中文测试文本用于估算令牌数量")
        self.assertGreater(n, 1)

    def test_longer_text_more_tokens(self):
        short = count_tokens("hello world")
        long = count_tokens("hello world " * 50)
        self.assertGreater(long, short)


class MatchPricingTest(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(_match_pricing("deepseek-chat"), MODEL_PRICING["deepseek-chat"])

    def test_prefix_match(self):
        # claude-sonnet-4-5-xxx 应匹配 claude-sonnet-4-5
        self.assertEqual(
            _match_pricing("claude-sonnet-4-5-thinking"),
            MODEL_PRICING["claude-sonnet-4-5"],
        )

    def test_case_insensitive(self):
        self.assertEqual(_match_pricing("DeepSeek-Chat"), MODEL_PRICING["deepseek-chat"])

    def test_empty_returns_default(self):
        self.assertEqual(_match_pricing(""), _DEFAULT_PRICING)

    def test_ollama_format_is_free(self):
        p = _match_pricing("qwen2.5:14b")
        self.assertEqual(p["input"], 0.0)
        self.assertEqual(p["output"], 0.0)

    def test_unknown_returns_default(self):
        self.assertEqual(_match_pricing("totally-unknown-model"), _DEFAULT_PRICING)


class CalculateCostTest(unittest.TestCase):
    def test_zero_tokens(self):
        self.assertEqual(calculate_cost("deepseek-chat"), 0.0)

    def test_input_output_cost(self):
        # deepseek-chat: input 0.27, output 1.10 per 1M
        cost = calculate_cost("deepseek-chat", input_tokens=1_000_000, output_tokens=1_000_000)
        self.assertAlmostEqual(cost, 0.27 + 1.10, places=6)

    def test_cache_hit_pricing(self):
        # 全部命中缓存：按 input_cache 0.07 计价
        cost = calculate_cost("deepseek-chat", cache_hit=1_000_000)
        self.assertAlmostEqual(cost, 0.07, places=6)

    def test_cache_split(self):
        cost = calculate_cost("deepseek-chat", cache_hit=500_000, cache_miss=500_000)
        expected = (500_000 * 0.07 + 500_000 * 0.27) / 1_000_000
        self.assertAlmostEqual(cost, expected, places=6)

    def test_reasoning_priced_separately(self):
        # deepseek-reasoner: output 2.19, reasoning 2.19
        cost = calculate_cost(
            "deepseek-reasoner", output_tokens=1_000_000, reasoning_tokens=400_000
        )
        # normal_out = 600k * 2.19 + 400k * 2.19 = 1M * 2.19
        self.assertAlmostEqual(cost, 2.19, places=6)

    def test_free_ollama_model(self):
        cost = calculate_cost("qwen2.5:14b", input_tokens=1_000_000, output_tokens=1_000_000)
        self.assertEqual(cost, 0.0)

    def test_from_stats_aliases(self):
        cost = calculate_cost_from_stats(
            "deepseek-chat",
            {"input_tokens": 1_000_000, "output_tokens": 0},
        )
        self.assertAlmostEqual(cost, 0.27, places=6)


class TokenOptimizerMessageTest(unittest.TestCase):
    def setUp(self):
        self.opt = TokenOptimizer()

    def test_calculate_message_tokens_simple(self):
        msgs = [{"role": "user", "content": "hello world"}]
        self.assertGreater(self.opt.calculate_message_tokens(msgs), 0)

    def test_calculate_message_tokens_multimodal_image(self):
        msgs = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {"type": "image_url", "image_url": {"url": "data:..."}},
            ],
        }]
        # 图片固定 765 token 开销
        self.assertGreaterEqual(self.opt.calculate_message_tokens(msgs), 765)

    def test_calculate_message_tokens_tool_calls(self):
        msgs = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "create_node", "arguments": '{"type":"box"}'}}
            ],
        }]
        self.assertGreater(self.opt.calculate_message_tokens(msgs), 0)

    def test_calculate_message_tokens_includes_tools_schema(self):
        msgs = [{"role": "user", "content": "create a box"}]
        tools = [{
            "type": "function",
            "function": {
                "name": "create_node",
                "description": "Create a Houdini node",
                "parameters": {
                    "type": "object",
                    "properties": {"node_type": {"type": "string"}},
                },
            },
        }]

        without_tools = self.opt.calculate_message_tokens(msgs)
        with_tools = self.opt.calculate_message_tokens(msgs, tools=tools)

        self.assertGreater(with_tools, without_tools)

    def test_estimate_message_tokens_breakdown_matches_total(self):
        msgs = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {"type": "image_url", "image_url": {"url": "data:..."}},
            ],
        }, {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "create_node", "arguments": '{"type":"box"}'}}
            ],
        }]
        tools = [{
            "type": "function",
            "function": {
                "description": "Create a Houdini node",
                "parameters": {"type": "object"},
            },
        }]

        estimate = self.opt.estimate_message_tokens(msgs, tools=tools)

        self.assertIsInstance(estimate, TokenEstimate)
        self.assertEqual(estimate.total, self.opt.calculate_message_tokens(msgs, tools=tools))
        self.assertGreater(estimate.text_tokens, 0)
        self.assertGreaterEqual(estimate.image_tokens, 765)
        self.assertGreater(estimate.tool_call_tokens, 0)
        self.assertGreater(estimate.message_overhead_tokens, 0)
        self.assertGreater(estimate.tool_definition_tokens, 0)

    def test_compress_tool_result_error(self):
        out = self.opt.compress_tool_result({"success": False, "error": "boom"})
        self.assertIn("boom", out)

    def test_compress_tool_result_short_success(self):
        out = self.opt.compress_tool_result({"success": True, "result": "ok"})
        self.assertEqual(out, "ok")

    def test_compress_tool_result_structured_success(self):
        out = self.opt.compress_tool_result({
            "success": True,
            "summary": "临时 Auto 验证完成: /obj/geo1/OUT points=4",
            "result": {"node_path": "/obj/geo1/OUT", "point_count": 4},
        })

        self.assertIn("points=4", out)
        self.assertIn("/obj/geo1/OUT", out)

    def test_compress_tool_result_empty(self):
        self.assertEqual(self.opt.compress_tool_result({}), "")

    def test_compress_tool_result_long_truncates(self):
        long_text = "line one\n" + "x" * 500 + "\nline last"
        out = self.opt.compress_tool_result(
            {"success": True, "result": long_text}, max_length=100
        )
        self.assertLess(len(out), len(long_text))


class CompressMessagesTest(unittest.TestCase):
    def setUp(self):
        self.opt = TokenOptimizer(TokenBudget(keep_recent_messages=2))

    def test_empty_messages(self):
        msgs, stats = self.opt.compress_messages([])
        self.assertEqual(msgs, [])
        self.assertEqual(stats["compressed"], 0)

    def test_fewer_than_keep_recent_untouched(self):
        msgs = [{"role": "user", "content": "a"}]
        out, stats = self.opt.compress_messages(msgs, keep_recent=4)
        self.assertEqual(out, msgs)
        self.assertEqual(stats["compressed"], 0)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["original_tokens"], stats["compressed_tokens"])
        self.assertEqual(stats["saved_percent"], 0.0)

    def test_compression_stats_to_dict(self):
        stats = CompressionStats.from_counts(
            compressed=3,
            kept=2,
            original_tokens=100,
            compressed_tokens=40,
            strategy=CompressionStrategy.BALANCED.value,
        )

        self.assertEqual(stats.saved_tokens, 60)
        self.assertEqual(stats.saved_percent, 60.0)
        self.assertEqual(stats.to_dict()["strategy"], "balanced")

    def test_compress_context_rounds_keeps_recent_rounds(self):
        messages = [
            {"role": "user", "content": "first request"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second request"},
            {"role": "assistant", "content": "second answer"},
            {"role": "user", "content": "third request"},
            {"role": "assistant", "content": "third answer"},
            {"role": "user", "content": "fourth request"},
        ]

        compressed, stats = self.opt.compress_context_rounds(messages, protect_recent_rounds=2)

        self.assertEqual(compressed[0]["role"], "system")
        self.assertIn("历史对话摘要", compressed[0]["content"])
        self.assertEqual([msg["content"] for msg in compressed[1:]], [
            "third request",
            "third answer",
            "fourth request",
        ])
        self.assertEqual(stats["compressed"], 4)
        self.assertEqual(stats["kept"], 3)
        self.assertEqual(stats["strategy"], "balanced")


class ContextRoundPlanTest(unittest.TestCase):
    def test_structured_assembly_keeps_named_suffix_order(self):
        assembly = build_context_assembly(
            [{"role": "system", "content": "prefix"}],
            [{"role": "user", "content": "history"}],
            [
                DynamicContextSection("rag", [{"role": "system", "content": "rag"}], 0),
                DynamicContextSection("memory", [{"role": "system", "content": "memory"}], 1),
                DynamicContextSection("plan", [{"role": "system", "content": "plan"}], 2),
                DynamicContextSection("reminder", [{"role": "system", "content": "reminder"}], 3),
            ],
        )

        self.assertEqual([m["content"] for m in assembly.messages()], [
            "prefix", "history", "rag", "memory", "plan", "reminder",
        ])

    def test_pruner_counts_tools_and_degrades_dynamic_sections_in_order(self):
        assembly = build_context_assembly(
            [{"role": "system", "content": "prefix"}],
            [{"role": "user", "content": "current body"}],
            [
                DynamicContextSection("rag", [{"role": "system", "content": "rag"}], 0),
                DynamicContextSection("plan", [{"role": "system", "content": "plan"}], 2),
            ],
        )
        tools = [{"type": "function", "function": {"description": "x" * 1000}}]
        seen_tools = []

        def count(messages, actual_tools):
            seen_tools.append(actual_tools)
            return len(messages) * 10 + (100 if actual_tools else 0)

        prune_context_assembly_to_token_target(assembly, 130, count, tools=tools, min_rounds=1)

        self.assertTrue(all(item is tools for item in seen_tools))
        self.assertEqual(assembly.dynamic_sections[0].messages, [])
        self.assertNotEqual(assembly.dynamic_sections[1].messages, [])

    def test_pruner_preserves_current_image_and_complete_tool_chain(self):
        old_image = [{"type": "text", "text": "old"}, {"type": "image_url", "image_url": {"url": "old"}}]
        current_image = [{"type": "text", "text": "current"}, {"type": "image_url", "image_url": {"url": "current"}}]
        assembly = build_context_assembly(history_messages=[
            {"role": "user", "content": old_image},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "function": {"name": "x", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "result"},
            {"role": "user", "content": current_image},
        ])

        prune_context_assembly_to_token_target(
            assembly, 1000, lambda messages, tools: len(messages), min_rounds=1,
        )
        result = assembly.messages()

        self.assertIsInstance(result[0]["content"], str)
        self.assertEqual(result[-1]["content"], current_image)
        self.assertEqual(result[1]["tool_calls"][0]["id"], result[2]["tool_call_id"])

    def test_pruner_reports_budget_unsatisfied_without_truncating_body(self):
        body = "x" * 1000
        assembly = build_context_assembly(
            [{"role": "system", "content": "required prefix"}],
            [{"role": "user", "content": body}],
        )
        result = prune_context_assembly_to_token_target(
            assembly,
            10,
            lambda messages, tools: sum(len(str(m.get("content", ""))) for m in messages),
            min_rounds=1,
        )
        self.assertFalse(result.within_budget)
        self.assertGreater(result.final_tokens, result.target_tokens)
        self.assertEqual(assembly.history_rounds[0][0]["content"], body)

    def test_manual_compression_keeps_recent_complete_round(self):
        opt = TokenOptimizer(TokenBudget(keep_recent_messages=2))
        messages = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "function": {"name": "x", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c", "content": "result"},
        ]

        compressed, _ = opt.compress_messages(messages, keep_recent=2)

        self.assertEqual([m.get("role") for m in compressed[-3:]], ["user", "assistant", "tool"])

    def test_plan_context_rounds_splits_on_user_messages(self):
        messages = [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "done"},
            {"role": "tool", "content": "result"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "done again"},
            {"role": "user", "content": "third"},
        ]

        plan = plan_context_rounds(messages, protect_recent_rounds=2)

        self.assertEqual(plan.old_round_count, 2)
        self.assertEqual(plan.protected_round_count, 2)
        self.assertEqual(plan.old_rounds[0][0]["role"], "system")
        self.assertEqual(plan.old_rounds[1][0]["content"], "first")
        self.assertEqual(plan.protected_rounds[0][0]["content"], "second")
        self.assertEqual(plan.protected_rounds[1][0]["content"], "third")
        self.assertEqual(plan.messages, messages)

    def test_plan_context_rounds_can_protect_none(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ]

        plan = plan_context_rounds(messages, protect_recent_rounds=0)

        self.assertEqual(plan.old_round_count, 2)
        self.assertEqual(plan.protected_round_count, 0)
        self.assertEqual(plan.old_messages, messages)
        self.assertEqual(plan.protected_messages, [])

    def test_flatten_context_rounds_preserves_order(self):
        rounds = [[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "one"},
        ], [
            {"role": "user", "content": "second"},
        ]]

        self.assertEqual([msg["content"] for msg in flatten_context_rounds(rounds)], [
            "first",
            "one",
            "second",
        ])

    def test_compress_old_round_tool_results_only_mutates_unprotected_tools(self):
        rounds = [[
            {"role": "user", "content": "old"},
            {"role": "tool", "content": "x" * 250},
        ], [
            {"role": "user", "content": "recent"},
            {"role": "tool", "content": "y" * 250},
        ]]

        count = compress_old_round_tool_results(
            rounds,
            protect_recent_rounds=1,
            summarize_fn=lambda content, limit: content[:limit] + "...[custom]",
        )

        self.assertEqual(count, 1)
        self.assertTrue(rounds[0][1]["content"].endswith("...[custom]"))
        self.assertEqual(rounds[1][1]["content"], "y" * 250)

    def test_compress_old_round_tool_results_without_summarizer_does_not_character_truncate(self):
        content = "x" * 250
        rounds = [[
            {"role": "user", "content": "old"},
            {"role": "tool", "content": content},
        ]]

        count = compress_old_round_tool_results(rounds, protect_recent_rounds=0)

        self.assertEqual(count, 0)
        self.assertEqual(rounds[0][1]["content"], content)

    def test_prune_context_rounds_check_before_pop(self):
        rounds = [[{"role": "user", "content": "one"}], [{"role": "user", "content": "two"}]]

        removed = prune_context_rounds_to_token_target(
            rounds,
            target_tokens=10,
            count_tokens_fn=lambda messages: len(messages),
            min_rounds=1,
            check_before_pop=True,
        )

        self.assertEqual(removed, 0)
        self.assertEqual(len(rounds), 2)

    def test_prune_context_rounds_pop_before_check(self):
        rounds = [[{"role": "user", "content": "one"}], [{"role": "user", "content": "two"}]]

        removed = prune_context_rounds_to_token_target(
            rounds,
            target_tokens=10,
            count_tokens_fn=lambda messages: len(messages),
            min_rounds=1,
            check_before_pop=False,
        )

        self.assertEqual(removed, 1)
        self.assertEqual([round_messages[0]["content"] for round_messages in rounds], ["two"])

    def test_assemble_context_messages_preserves_sections(self):
        rounds = [[{"role": "user", "content": "body"}]]
        assembled = assemble_context_messages(
            rounds,
            prefix_messages=[{"role": "system", "content": "prefix"}],
            summary_message={"role": "system", "content": "summary"},
            suffix_messages=[{"role": "user", "content": "suffix"}],
        )

        self.assertEqual([msg["content"] for msg in assembled], [
            "prefix",
            "summary",
            "body",
            "suffix",
        ])


class TokenBudgetTest(unittest.TestCase):
    def test_defaults(self):
        b = TokenBudget()
        self.assertEqual(b.strategy, CompressionStrategy.BALANCED)
        self.assertGreater(b.max_tokens, 0)
        self.assertTrue(0 < b.compression_threshold <= 1)

    def test_compression_strategy_controls_automatic_pruning(self):
        b = TokenBudget()

        aggressive = b.automatic_pruning_policy(CompressionStrategy.AGGRESSIVE)
        balanced = b.automatic_pruning_policy(CompressionStrategy.BALANCED)
        conservative = b.automatic_pruning_policy(CompressionStrategy.CONSERVATIVE)

        self.assertLess(aggressive.target_ratio, balanced.target_ratio)
        self.assertLess(balanced.target_ratio, conservative.target_ratio)
        self.assertLess(aggressive.protect_ratio, balanced.protect_ratio)
        self.assertLess(balanced.protect_ratio, conservative.protect_ratio)


if __name__ == "__main__":
    unittest.main()
