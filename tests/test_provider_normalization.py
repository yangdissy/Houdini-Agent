# -*- coding: utf-8 -*-
"""Table-driven provider normalization tests."""

import unittest

from houdini_agent.utils.provider_normalization import (
    model_capabilities,
    normalize_model_id,
    normalize_openai_parameters,
    protocol_for,
)


class ProviderNormalizationTest(unittest.TestCase):
    def test_protocol_selection_table(self):
        cases = [
            ("openai", "gpt-5.2", "openai"),
            ("deepseek", "deepseek-v4-pro", "openai"),
            ("glm", "glm-4.7", "openai"),
            ("duojie", "glm-4.7", "anthropic"),
            ("duojie", "glm-5.1", "anthropic"),
            ("duojie", "claude-sonnet", "openai"),
            ("kimi_coding", "k3[1m]", "anthropic"),
        ]
        for provider, model, expected in cases:
            with self.subTest(provider=provider, model=model):
                self.assertEqual(protocol_for(provider, model), expected)

    def test_model_normalization_and_capabilities_table(self):
        cases = [
            (" k3[1m] ", "k3", True, "max_tokens", False),
            ("kimi-for-coding-highspeed", "kimi-for-coding-highspeed", True, "max_tokens", False),
            ("gpt-5.3-codex", "gpt-5.3-codex", True, "max_completion_tokens", False),
            ("o3-mini", "o3-mini", False, "max_completion_tokens", False),
            ("DeepSeek-R1", "DeepSeek-R1", False, "max_tokens", True),
            ("deepseek-v4-pro", "deepseek-v4-pro", False, "max_tokens", True),
            ("deepseek-v4-flash", "deepseek-v4-flash", False, "max_tokens", False),
            ("glm-4.7", "glm-4.7", False, "max_tokens", True),
        ]
        for model, normalized, temp_one, token_parameter, reasoning in cases:
            with self.subTest(model=model):
                capabilities = model_capabilities(model)
                self.assertEqual(normalize_model_id(model), normalized)
                self.assertEqual(capabilities.temperature_one, temp_one)
                self.assertEqual(capabilities.max_tokens_parameter, token_parameter)
                self.assertEqual(capabilities.reasoning, reasoning)

    def test_openai_parameter_normalization_table(self):
        cases = [
            ("openai", "gpt-5.2", 0.17, 4096, True, False,
             {"temperature": 1, "max_completion_tokens": 4096}),
            ("openai", "chatgpt-4o-latest", 1.7, 4096, True, False,
             {"temperature": 1.0, "max_tokens": 4096}),
            ("deepseek", "deepseek-v4-pro", 0.2, 8192, True, False,
             {"temperature": 0.2, "max_tokens": 8192, "thinking": {"type": "enabled"}, "reasoning_effort": "high"}),
            ("deepseek", "deepseek-v4-flash", 0.2, None, True, False,
             {"temperature": 0.2, "thinking": {"type": "enabled"}}),
            ("siliconflow", "deepseek-ai/DeepSeek-V4-Pro", None, None, True, False,
             {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}),
            ("glm", "glm-4.7", 0.17, None, True, True,
             {"temperature": 0.17, "thinking": {"type": "enabled"}, "tool_stream": True}),
            ("duojie", "glm-4.7", 0.17, None, True, True,
             {"temperature": 0.17}),
            ("deepseek", "deepseek-v4-pro", 0.2, None, False, False,
             {"temperature": 0.2}),
        ]
        for provider, model, temperature, max_tokens, thinking, tools, expected in cases:
            with self.subTest(provider=provider, model=model):
                self.assertEqual(
                    normalize_openai_parameters(provider, model, temperature, max_tokens, thinking, tools),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()