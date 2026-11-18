# -*- coding: utf-8 -*-
"""Regression tests for NetworkBox-aware network text rendering."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs

_install_hou_stub()
_install_thirdparty_stubs()

from houdini_agent.utils.mcp.client import HoudiniMCP


_NODES = [
    {"path": "/obj/geo/a", "name": "a", "type": "Sop/grid", "position": [0, 0],
     "inputs": [], "outputs": ["/obj/geo/b"], "parameters": {}, "flags": {}},
    {"path": "/obj/geo/b", "name": "b", "type": "Sop/null", "position": [1, 0],
     "inputs": ["/obj/geo/a"], "outputs": ["/obj/geo/out"], "parameters": {}, "flags": {}},
    {"path": "/obj/geo/out", "name": "out", "type": "Sop/null", "position": [2, 0],
     "inputs": ["/obj/geo/b"], "outputs": [], "parameters": {}, "flags": {}},
]
_CONNECTIONS = [
    {"from": "/obj/geo/a", "to": "/obj/geo/b", "input_index": 0},
    {"from": "/obj/geo/b", "to": "/obj/geo/out", "input_index": 0},
]


class NetworkStructureTextTest(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(HoudiniMCP)

    def _data(self, boxes):
        return {
            "network_path": "/obj/geo", "network_type": "geo", "node_count": 3,
            "nodes": list(_NODES), "connections": list(_CONNECTIONS),
            "network_boxes": boxes,
            "boxed_node_paths": [path for box in boxes for path in box["nodes"]],
        }

    def test_box_overview_collapses_boxed_nodes_and_lists_unboxed_nodes(self):
        data = self._data([{
            "name": "setup", "comment": "build source", "node_count": 2,
            "nodes": ["/obj/geo/a", "/obj/geo/b"], "minimized": False,
        }])
        with patch.object(self.client, "get_network_structure", return_value=(True, data)):
            ok, text = self.client.get_network_structure_text("/obj/geo")
        self.assertTrue(ok)
        self.assertIn("### NetworkBox 概览:", text)
        self.assertIn("**setup**: build source — 2 个节点", text)
        self.assertIn("### 未分组节点 (1 个):", text)
        self.assertNotIn("### 所有节点:", text)

    def test_box_name_drills_into_only_target_and_reports_cross_connections(self):
        data = self._data([{
            "name": "setup", "comment": "build source", "node_count": 2,
            "nodes": ["/obj/geo/a", "/obj/geo/b"], "minimized": False,
        }])
        with patch.object(self.client, "get_network_structure", return_value=(True, data)):
            ok, text = self.client.get_network_structure_text("/obj/geo", "setup")
        self.assertTrue(ok)
        self.assertIn("## NetworkBox 详情: setup", text)
        self.assertIn("### 内部连接:", text)
        self.assertIn("### 跨组连接", text)
        self.assertNotIn("### NetworkBox 概览:", text)

    def test_no_boxes_keeps_legacy_full_expansion(self):
        data = self._data([])
        with patch.object(self.client, "get_network_structure", return_value=(True, data)):
            ok, text = self.client.get_network_structure_text("/obj/geo")
        self.assertTrue(ok)
        self.assertIn("## 网络结构: /obj/geo", text)
        self.assertIn("### 节点列表:", text)
        self.assertNotIn("NetworkBox 概览", text)


if __name__ == "__main__":
    unittest.main()
