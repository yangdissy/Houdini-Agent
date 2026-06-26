# -*- coding: utf-8 -*-
"""Markdown code fence parsing tests."""

import unittest

from tests.test_import_smoke import _install_qt_stubs

_install_qt_stubs()

from houdini_agent.ui.cursor_widgets import SimpleMarkdown  # noqa: E402


class MarkdownCodeFenceTest(unittest.TestCase):
    def test_inline_language_code_fence(self):
        segments = SimpleMarkdown.parse_segments("```c\nfloat amp = chf(\"amp\");\n```")

        self.assertEqual(segments, [('code', 'c', 'float amp = chf("amp");')])

    def test_split_language_code_fence(self):
        segments = SimpleMarkdown.parse_segments("```\nc\nfloat amp = chf(\"amp\");\n```")

        self.assertEqual(segments, [('code', 'c', 'float amp = chf("amp");')])


if __name__ == "__main__":
    unittest.main()
