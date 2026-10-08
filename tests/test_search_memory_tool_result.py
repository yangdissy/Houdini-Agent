# -*- coding: utf-8 -*-
"""Regression tests for the search_memory tool response contract."""

import json
import unittest
from unittest import mock

from tests.test_import_smoke import (
    _install_hou_stub,
    _install_qt_stubs,
    _install_thirdparty_stubs,
)

_install_hou_stub()
_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.utils.mcp.client import HoudiniMCP


class _Embedder:
    is_semantic = False


class _PersonalStore:
    embedder = _Embedder()

    def count_semantic(self):
        return 0

    def count_episodic(self):
        return 0

    def count_procedural(self):
        return 0

    def search_all_levels(self, **_kwargs):
        return []

    def search_episodic(self, **_kwargs):
        return []

    def search_procedural(self, **_kwargs):
        return []


class _TeamRecord:
    id = "team-1"
    rule = "Pyro expansion can enlarge the flame head."
    category = "knowledge"
    abstraction_level = 2
    confidence = 0.9
    source_users = ["artist"]


class _TeamStore:
    def __init__(self, with_result):
        self.with_result = with_result

    def search_semantic(self, **_kwargs):
        return [(_TeamRecord(), 0.5)] if self.with_result else []

    def search_procedural(self, **_kwargs):
        return []


class SearchMemoryToolResultTest(unittest.TestCase):
    def _search(self, with_team_result):
        client = object.__new__(HoudiniMCP)
        client._username = "tester"
        with mock.patch(
            "houdini_agent.utils.memory_store.get_memory_store",
            return_value=_PersonalStore(),
        ), mock.patch(
            "houdini_agent.utils.team_memory_store.get_team_memory_store",
            return_value=_TeamStore(with_team_result),
        ):
            return client._tool_search_memory({"query": "Pyro mushroom head", "top_k": 5})

    def test_team_results_are_exposed_in_result_text(self):
        response = self._search(with_team_result=True)

        payload = json.loads(response["result"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["semantic_memories"][0]["source"], "team")
        self.assertEqual(payload["semantic_memories"][0]["contributors"], ["artist"])

    def test_empty_search_still_exposes_result_text(self):
        response = self._search(with_team_result=False)

        payload = json.loads(response["result"])
        self.assertEqual(payload["count"], 0)
        self.assertIn("未找到相关记忆", payload["message"])


if __name__ == "__main__":
    unittest.main()