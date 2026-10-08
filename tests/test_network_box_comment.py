# -*- coding: utf-8 -*-
"""Tests for updating an existing NetworkBox comment in place."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs

_install_hou_stub()
_install_thirdparty_stubs()

from houdini_agent.utils.mcp import hou_core
from houdini_agent.utils.mcp.client import HoudiniMCP


class _Box:
    def __init__(self, name, comment=""):
        self._name = name
        self._comment = comment

    def name(self):
        return self._name

    def comment(self):
        return self._comment

    def setComment(self, comment):
        self._comment = comment


class _Parent:
    def __init__(self, path, boxes):
        self._path = path
        self._boxes = boxes

    def path(self):
        return self._path

    def networkBoxes(self):
        return tuple(self._boxes)


class NetworkBoxCommentTest(unittest.TestCase):
    def test_set_network_box_comment_updates_exact_box_and_supports_clearing(self):
        target = _Box("processing", "old")
        other = _Box("processing_extra", "keep")
        parent = _Parent("/obj/project", [target, other])
        fake_hou = type("Hou", (), {"node": staticmethod(lambda path: parent)})()

        with patch.object(hou_core, "hou", fake_hou):
            ok, message, details = hou_core.set_network_box_comment(
                parent.path(), "processing", ""
            )

        self.assertTrue(ok, message)
        self.assertEqual(target.comment(), "")
        self.assertEqual(other.comment(), "keep")
        self.assertEqual(details, {
            "box_name": "processing", "old_comment": "old", "new_comment": "",
        })

    def test_tool_returns_verified_readback(self):
        client = object.__new__(HoudiniMCP)
        with patch.object(
            hou_core,
            "set_network_box_comment",
            return_value=(True, "ok", {
                "box_name": "processing", "old_comment": "", "new_comment": "cleanup",
            }),
        ):
            result = HoudiniMCP._tool_set_network_box_comment(client, {
                "parent_path": "/obj/project",
                "box_name": "processing",
                "comment": "cleanup",
            })

        self.assertTrue(result["success"])
        self.assertEqual(result["verification"], {
            "status": "verified",
            "parent_path": "/obj/project",
            "box_name": "processing",
            "old_comment": "",
            "actual_comment": "cleanup",
        })

    def test_set_network_box_comment_fails_closed_for_missing_or_duplicate_name(self):
        first = _Box("processing", "first")
        second = _Box("processing", "second")
        parent = _Parent("/obj/project", [first, second])
        fake_hou = type("Hou", (), {"node": staticmethod(lambda path: parent)})()

        with patch.object(hou_core, "hou", fake_hou):
            duplicate = hou_core.set_network_box_comment(
                parent.path(), "processing", "changed"
            )
            missing = hou_core.set_network_box_comment(
                parent.path(), "missing", "changed"
            )

        self.assertFalse(duplicate[0])
        self.assertFalse(missing[0])
        self.assertEqual(first.comment(), "first")
        self.assertEqual(second.comment(), "second")


if __name__ == "__main__":
    unittest.main()