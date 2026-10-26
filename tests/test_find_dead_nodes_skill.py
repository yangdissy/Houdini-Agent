# -*- coding: utf-8 -*-
"""Regression tests for the find_dead_nodes skill."""

import sys
from pathlib import Path
from types import SimpleNamespace

from houdini_agent import skills


def _entrypoint():
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "graph" / "find_dead_nodes" / "SKILL.md"
    )
    return skills._load_descriptor_entrypoint(descriptor)


class _NodeType:
    def name(self):
        return "shop_materialpath"


class _ShopNode:
    def name(self):
        return "material1"

    def path(self):
        return "/mat/matnet1/material1"

    def type(self):
        return _NodeType()

    def inputs(self):
        return ()

    def outputs(self):
        return ()

    def errors(self):
        return ()

    def warnings(self):
        return ()


def test_shop_node_without_display_flag_api_is_reported(monkeypatch):
    network = SimpleNamespace(children=lambda: (_ShopNode(),))
    monkeypatch.setitem(sys.modules, "hou", SimpleNamespace(node=lambda path: network))

    result = _entrypoint().run("/mat/matnet1")

    assert result["dead_node_count"] == 1
    assert result["orphan_nodes"][0]["path"] == "/mat/matnet1/material1"