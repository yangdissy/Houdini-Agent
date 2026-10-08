# -*- coding: utf-8 -*-
"""Parameter reference inspection contract tests."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs


_install_hou_stub()
_install_thirdparty_stubs()

import houdini_agent.utils.mcp.client as mcp_client
from houdini_agent.utils.mcp.client import HoudiniMCP


class _Parm:
    def __init__(self, path, references=None):
        self._path = path
        self._references = references or []

    def path(self):
        return self._path

    def parmsReferencingThis(self):
        return self._references


class _Node:
    def __init__(self, parm):
        self._parm = parm

    def parm(self, name):
        return self._parm if name == "sizex" else None


class ParameterReferenceTest(unittest.TestCase):
    def test_finds_exact_component_references_in_stable_order(self):
        target = _Parm("/obj/geo1/box1/sizex", [
            _Parm("/obj/geo1/xform1/tx"),
            _Parm("/obj/geo1/copy1/scale"),
            _Parm("/obj/geo1/xform1/tx"),
        ])
        fake_hou = type("Hou", (), {"node": staticmethod(lambda path: _Node(target))})()

        with patch.object(mcp_client, "hou", fake_hou):
            result = HoudiniMCP().find_parameter_references("/obj/geo1/box1", "sizex")

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["target_parm_path"], "/obj/geo1/box1/sizex")
        self.assertEqual(result["data"]["reference_count"], 2)
        self.assertEqual(result["data"]["references"], [
            "/obj/geo1/copy1/scale",
            "/obj/geo1/xform1/tx",
        ])

    def test_sets_relative_channel_reference_through_expression_writer(self):
        mcp = HoudiniMCP()
        snapshot = {"old_value": 1.0, "new_value": {"expr": 'ch("../box1/sizex")'}}

        with patch.object(
            mcp,
            "set_parameter_expression",
            return_value=(True, "ok", snapshot),
        ) as writer, patch.object(
            mcp_client.hou.text,
            "relpath",
            return_value="../box1/sizex",
        ):
            ok, message, actual_snapshot = mcp.set_parameter_reference(
                "/obj/geo1/xform1", "tx", "/obj/geo1/box1", "sizex"
            )

        self.assertTrue(ok)
        self.assertEqual(message, "ok")
        self.assertEqual(actual_snapshot, snapshot)
        writer.assert_called_once_with(
            "/obj/geo1/xform1", "tx", 'ch("../box1/sizex")', "hscript"
        )


if __name__ == "__main__":
    unittest.main()