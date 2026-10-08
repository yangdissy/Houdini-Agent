# -*- coding: utf-8 -*-
"""Multiparm instance management contract tests."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs


_install_hou_stub()
_install_thirdparty_stubs()

import houdini_agent.utils.mcp.client as mcp_client
from houdini_agent.utils.mcp.client import HoudiniMCP


class _InstanceParm:
    def __init__(self, path, index):
        self._path = path
        self._index = index

    def path(self):
        return self._path

    def multiParmInstanceIndices(self):
        return (self._index,)


class _Multiparm:
    def __init__(self):
        self.inserted = []
        self.removed = []

    def evalAsInt(self):
        return 2

    def multiParmInstances(self):
        return [
            _InstanceParm("/obj/geo1/test1/item1", 0),
            _InstanceParm("/obj/geo1/test1/value1", 0),
            _InstanceParm("/obj/geo1/test1/item2", 1),
            _InstanceParm("/obj/geo1/test1/value2", 1),
        ]

    def insertMultiParmInstance(self, index):
        self.inserted.append(index)

    def removeMultiParmInstance(self, index):
        self.removed.append(index)


class _Node:
    def __init__(self, multiparm=None):
        self.multiparm = multiparm or _Multiparm()

    def parm(self, name):
        return self.multiparm if name == "items" else None


class MultiparmManagementTest(unittest.TestCase):
    def test_lists_instance_parameter_paths_grouped_by_instance(self):
        fake_hou = type("Hou", (), {"node": staticmethod(lambda path: _Node())})()

        with patch.object(mcp_client, "hou", fake_hou):
            result = HoudiniMCP().list_multiparm_instances("/obj/geo1/test1", "items")

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["instance_count"], 2)
        self.assertEqual(result["data"]["instances"], [
            {
                "index": 0,
                "parameter_paths": [
                    "/obj/geo1/test1/item1",
                    "/obj/geo1/test1/value1",
                ],
            },
            {
                "index": 1,
                "parameter_paths": [
                    "/obj/geo1/test1/item2",
                    "/obj/geo1/test1/value2",
                ],
            },
        ])

    def test_inserts_instance_at_valid_zero_based_index(self):
        multiparm = _Multiparm()
        fake_hou = type("Hou", (), {"node": staticmethod(lambda path: _Node(multiparm))})()

        with patch.object(mcp_client, "hou", fake_hou):
            ok, message, snapshot = HoudiniMCP().insert_multiparm_instance(
                "/obj/geo1/test1", "items", 1
            )

        self.assertTrue(ok)
        self.assertEqual(multiparm.inserted, [1])
        self.assertEqual(snapshot, {
            "node_path": "/obj/geo1/test1",
            "param_name": "items",
            "operation": "insert",
            "index": 1,
            "old_count": 2,
            "new_count": 3,
            "is_multiparm": True,
        })

    def test_rejects_out_of_range_insert_before_mutation(self):
        multiparm = _Multiparm()
        fake_hou = type("Hou", (), {"node": staticmethod(lambda path: _Node(multiparm))})()

        with patch.object(mcp_client, "hou", fake_hou):
            ok, message, snapshot = HoudiniMCP().insert_multiparm_instance(
                "/obj/geo1/test1", "items", 3
            )

        self.assertFalse(ok)
        self.assertIn("允许 0 到 2", message)
        self.assertIsNone(snapshot)
        self.assertEqual(multiparm.inserted, [])

    def test_removes_instance_at_valid_zero_based_index(self):
        multiparm = _Multiparm()
        fake_hou = type("Hou", (), {"node": staticmethod(lambda path: _Node(multiparm))})()

        with patch.object(mcp_client, "hou", fake_hou):
            ok, message, snapshot = HoudiniMCP().remove_multiparm_instance(
                "/obj/geo1/test1", "items", 1
            )

        self.assertTrue(ok)
        self.assertEqual(multiparm.removed, [1])
        self.assertEqual(snapshot, {
            "node_path": "/obj/geo1/test1",
            "param_name": "items",
            "operation": "remove",
            "index": 1,
            "old_count": 2,
            "new_count": 1,
            "is_multiparm": True,
        })


if __name__ == "__main__":
    unittest.main()