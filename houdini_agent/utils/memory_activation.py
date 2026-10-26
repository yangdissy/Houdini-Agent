# -*- coding: utf-8 -*-
"""Pure ranking helpers for long-term memory activation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Sequence


def parse_memory_usage(text: str, aliases: Sequence[str]) -> set[str] | None:
    clean = re.sub(r"<think>[\s\S]*?</think>", "", text or "")
    matches = list(re.finditer(r"(?m)^\[mem-used:\s*([^\]\n]*)\]\s*$", clean))
    if len(matches) != 1 or clean[matches[0].end():].strip():
        return None
    declaration = matches[0].group(1).strip()
    if declaration == "none":
        return set()
    tokens = [token.strip() for token in declaration.split(",")]
    if not tokens or len(set(tokens)) != len(tokens):
        return None
    if any(not re.fullmatch(r"M[1-9][0-9]*", token) for token in tokens):
        return None
    return set(tokens) if set(tokens).issubset(aliases) else None


def strip_memory_usage(text: str, streaming: bool = False) -> str:
    clean = re.sub(r"(?m)^\[mem-used:[^\]\n]*\][ \t]*(?:\r?\n|$)", "", text or "")
    if streaming:
        tail = clean.rsplit("\n", 1)[-1]
        if tail and ("[mem-used:".startswith(tail) or tail.startswith("[mem-used:")):
            clean = clean[:-len(tail)]
    return clean


@dataclass
class MemoryActivationCandidate:
    """One candidate memory line before prompt injection."""

    kind: str
    text: str
    score: float
    priority: float = 1.0
    confidence: float = 0.5
    record_id: str = ""
    source: object = None


class MemoryActivationSelector:
    """Select diverse, high-value memories under a prompt budget."""

    def __init__(self, max_chars: int = 900, redundancy_threshold: float = 0.86):
        self.max_chars = max_chars
        self.redundancy_threshold = redundancy_threshold

    def select(self, candidates: Sequence[MemoryActivationCandidate]) -> List[MemoryActivationCandidate]:
        if not candidates:
            return []

        ranked = sorted(candidates, key=self._rank_key, reverse=True)
        selected: List[MemoryActivationCandidate] = []
        used_chars = 0

        for candidate in ranked:
            line_cost = len(candidate.text) + 1
            if selected and used_chars + line_cost > self.max_chars:
                continue
            if self._is_redundant(candidate, selected):
                continue
            selected.append(candidate)
            used_chars += line_cost

        return selected

    @staticmethod
    def _rank_key(candidate: MemoryActivationCandidate):
        confidence = max(0.0, min(1.0, candidate.confidence))
        priority = max(0.0, candidate.priority)
        score = max(0.0, candidate.score)
        return score * (0.60 + 0.25 * confidence + 0.15 * priority)

    def _is_redundant(
        self,
        candidate: MemoryActivationCandidate,
        selected: Sequence[MemoryActivationCandidate],
    ) -> bool:
        needle = self._normalize(candidate.text)
        if not needle:
            return True
        for existing in selected:
            haystack = self._normalize(existing.text)
            if needle == haystack:
                return True
            if needle in haystack or haystack in needle:
                shorter = min(len(needle), len(haystack))
                longer = max(len(needle), len(haystack))
                if shorter / max(1, longer) >= 0.62:
                    return True
            if SequenceMatcher(None, needle, haystack).ratio() >= self.redundancy_threshold:
                return True
        return False

    @staticmethod
    def _normalize(text: str) -> str:
        text = (text or "").lower()
        text = re.sub(r"\[[^\]]+\]", " ", text)
        text = re.sub(r"\(conf=[^)]+\)", " ", text)
        text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()