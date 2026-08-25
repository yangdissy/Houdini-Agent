import unittest

from houdini_agent.ui.slash_commands import parse_slash_command


class SlashCommandTest(unittest.TestCase):
    def test_parser_preserves_natural_language_argument(self):
        self.assertEqual(
            parse_slash_command("/remember  始终使用中文 回答 "),
            ("remember", "始终使用中文 回答"),
        )

    def test_parser_ignores_normal_chat_text(self):
        self.assertIsNone(parse_slash_command("请记住这个偏好"))


if __name__ == "__main__":
    unittest.main()

