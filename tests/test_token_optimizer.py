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
    CompressionStrategy,
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


class TokenBudgetTest(unittest.TestCase):
    def test_defaults(self):
        b = TokenBudget()
        self.assertEqual(b.strategy, CompressionStrategy.BALANCED)
        self.assertGreater(b.max_tokens, 0)
        self.assertTrue(0 < b.compression_threshold <= 1)


if __name__ == "__main__":
    unittest.main()
