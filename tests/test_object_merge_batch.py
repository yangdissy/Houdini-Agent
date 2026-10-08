# -*- coding: utf-8 -*-
"""Object Merge batch creation contract tests."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs


_install_hou_stub()
_install_thirdparty_stubs()

import houdini_agent.utils.mcp.client as mcp_client
from houdini_agent.utils.mcp.client import HoudiniMCP


class _Node:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class ObjectMergeBatchTest(unittest.TestCase):
    def test_creates_one_relative_object_merge_per_source(self):
        mcp = object.__new__(HoudiniMCP)
        plans = []
        mcp.create_network = lambda plan: plans.append(plan) or (True, "ok")
        nodes = {
            "/obj/geo1": _Node("/obj/geo1"),
            "/obj/source_a/OUT": _Node("/obj/source_a/OUT"),
            "/obj/source_b/OUT": _Node("/obj/source_b/OUT"),
        }
        fake_hou = type("Hou", (), {
            "node": staticmethod(nodes.get),
            "text": type("Text", (), {
                "relpath": staticmethod(lambda source, target: source.replace("/obj/", "../")),
            })(),
        })()

        with patch.object(mcp_client, "hou", fake_hou):
            ok, message, snapshot = mcp.create_object_merges_batch(
                "/obj/geo1",
                ["/obj/source_a/OUT", "/obj/source_b/OUT"],
            )

        self.assertTrue(ok)
        self.assertEqual(message, "ok")
        self.assertEqual(plans, [{
            "parent_path": "/obj/geo1",
            "dry_run": False,
            "connections": [],
            "nodes": [
                {"id": "object_merge_1", "type": "object_merge", "parameters": {"objpath1": "../source_a/OUT"}},
                {"id": "object_merge_2", "type": "object_merge", "parameters": {"objpath1": "../source_b/OUT"}},
            ],
        }])
        self.assertEqual(snapshot["created_count"], 2)

    def test_missing_source_fails_before_network_mutation(self):
        mcp = object.__new__(HoudiniMCP)
        plans = []
        mcp.create_network = lambda plan: plans.append(plan) or (True, "ok")
        nodes = {"/obj/geo1": _Node("/obj/geo1")}
        fake_hou = type("Hou", (), {"node": staticmethod(nodes.get)})()

        with patch.object(mcp_client, "hou", fake_hou):
            ok, message, snapshot = mcp.create_object_merges_batch(
                "/obj/geo1", ["/obj/missing/OUT"]
            )

        self.assertFalse(ok)
        self.assertIn("未找到来源节点", message)
        self.assertIsNone(snapshot)
        self.assertEqual(plans, [])


if __name__ == "__main__":
    unittest.main()