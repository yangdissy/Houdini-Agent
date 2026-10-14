import unittest

from houdini_agent.ui.slash_commands import SLASH_COMMANDS_WITH_ARGS, parse_slash_command


class SlashCommandTest(unittest.TestCase):
    def test_parser_preserves_natural_language_argument(self):
        self.assertEqual(
            parse_slash_command("/remember  始终使用中文 回答 "),
            ("remember", "始终使用中文 回答"),
        )

    def test_parser_ignores_normal_chat_text(self):
        self.assertIsNone(parse_slash_command("请记住这个偏好"))

    def test_create_skill_preserves_natural_language_intent(self):
        self.assertIn("create_skill", SLASH_COMMANDS_WITH_ARGS)
        self.assertEqual(
            parse_slash_command("/create_skill  检查 UV 重叠并返回问题 primitive "),
            ("create_skill", "检查 UV 重叠并返回问题 primitive"),
        )

if __name__ == "__main__":
    unittest.main()

