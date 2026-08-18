# -*- coding: utf-8 -*-
"""Pure streaming parser for ``<think>`` blocks."""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ThinkingStreamEvent:
    """A semantic event emitted while parsing an assistant text stream."""

    kind: str
    text: str = ""


class ThinkingStreamParser:
    """Parse split ``<think>`` tags without depending on Qt or UI state."""

    def __init__(self) -> None:
        self._buffer = ""
        self._in_thinking = False

    @property
    def in_thinking(self) -> bool:
        return self._in_thinking

    @staticmethod
    def _partial_tag_at_end(text: str, tag: str) -> int:
        for size in range(min(len(tag) - 1, len(text)), 0, -1):
            if tag[:size] == text[-size:]:
                return size
        return 0

    def feed(self, text: str) -> List[ThinkingStreamEvent]:
        """Consume one chunk and return ordered semantic events."""
        if text:
            self._buffer += text
        events: List[ThinkingStreamEvent] = []

        while self._buffer:
            tag = "</think>" if self._in_thinking else "<think>"
            position = self._buffer.find(tag)
            kind = "thinking" if self._in_thinking else "content"

            if position >= 0:
                if position:
                    events.append(ThinkingStreamEvent(kind, self._buffer[:position]))
                self._buffer = self._buffer[position + len(tag):]
                self._in_thinking = not self._in_thinking
                events.append(ThinkingStreamEvent(
                    "thinking_start" if self._in_thinking else "thinking_end"
                ))
                continue

            hold = self._partial_tag_at_end(self._buffer, tag)
            safe = self._buffer[:-hold] if hold else self._buffer
            if safe:
                events.append(ThinkingStreamEvent(kind, safe))
            self._buffer = self._buffer[-hold:] if hold else ""
            break

        return events

    def finish(self) -> List[ThinkingStreamEvent]:
        """Flush an incomplete tag or unclosed thinking block at stream end."""
        events: List[ThinkingStreamEvent] = []
        if self._buffer:
            events.append(ThinkingStreamEvent(
                "thinking" if self._in_thinking else "content",
                self._buffer,
            ))
            self._buffer = ""
        if self._in_thinking:
            self._in_thinking = False
            events.append(ThinkingStreamEvent("thinking_end"))
        return events