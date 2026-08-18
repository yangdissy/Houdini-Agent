# -*- coding: utf-8 -*-
"""Tests for the pure thinking stream parser."""

import unittest

from houdini_agent.core.thinking_stream_parser import ThinkingStreamParser


class ThinkingStreamParserTest(unittest.TestCase):
    @staticmethod
    def _pairs(events):
        return [(event.kind, event.text) for event in events]

    def test_plain_content_passes_through(self):
        parser = ThinkingStreamParser()
        self.assertEqual(self._pairs(parser.feed("hello")), [("content", "hello")])

    def test_complete_thinking_block_preserves_event_order(self):
        parser = ThinkingStreamParser()
        events = parser.feed("before<think>reason</think>after")
        self.assertEqual(self._pairs(events), [
            ("content", "before"),
            ("thinking_start", ""),
            ("thinking", "reason"),
            ("thinking_end", ""),
            ("content", "after"),
        ])

    def test_tags_can_be_split_at_every_character(self):
        source = "A<think>B</think>C"
        expected = [
            ("content", "A"),
            ("thinking_start", ""),
            ("thinking", "B"),
            ("thinking_end", ""),
            ("content", "C"),
        ]
        for split in range(1, len(source)):
            with self.subTest(split=split):
                parser = ThinkingStreamParser()
                events = parser.feed(source[:split]) + parser.feed(source[split:])
                self.assertEqual(self._pairs(events), expected)

    def test_finish_flushes_unclosed_thinking_content_and_end(self):
        parser = ThinkingStreamParser()
        events = parser.feed("<think>reason") + parser.finish()
        self.assertEqual(self._pairs(events), [
            ("thinking_start", ""),
            ("thinking", "reason"),
            ("thinking_end", ""),
        ])
        self.assertFalse(parser.in_thinking)

    def test_finish_treats_partial_open_tag_as_content(self):
        parser = ThinkingStreamParser()
        events = parser.feed("hello<th") + parser.finish()
        self.assertEqual(self._pairs(events), [
            ("content", "hello"),
            ("content", "<th"),
        ])


if __name__ == "__main__":
    unittest.main()