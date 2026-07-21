# -*- coding: utf-8 -*-
"""Geometry validation signal tests."""

import unittest

from tests.test_import_smoke import _install_thirdparty_stubs


_install_thirdparty_stubs()

import houdini_agent.utils.mcp.client as mcp_client


class _ModeValue:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _UpdateMode:
    Manual = _ModeValue("Manual")
    Auto = _ModeValue("Auto")


class _NodeType:
    def name(self):
        return "null"


class _BoundingBox:
    def minvec(self):
        return (0.0, 0.0, 0.0)

    def maxvec(self):
        return (0.0, 0.0, 0.0)

    def sizevec(self):
        return (0.0, 0.0, 0.0)

    def center(self):
        return (0.0, 0.0, 0.0)


class _Geometry:
    def __init__(self, point_count=0, primitive_count=0, vertex_count=0):
        self._counts = {
            "pointcount": point_count,
            "primitivecount": primitive_count,
            "vertexcount": vertex_count,
        }

    def intrinsicValue(self, name):
        return self._counts[name]

    def boundingBox(self):
        return _BoundingBox()


class _Node:
    def __init__(self, geometry):
        self._geometry = geometry
        self.cook_calls = []

    def path(self):
        return "/obj/geo1/OUT"

    def name(self):
        return "OUT"

    def type(self):
        return _NodeType()

    def needsToCook(self):
        return False

    def cook(self, force=False):
        self.cook_calls.append(force)

    def geometry(self):
        return self._geometry

    def errors(self):
        return []

    def warnings(self):
        return []

    def isDisplayFlagSet(self):
        return True

    def isRenderFlagSet(self):
        return True

    def isBypassed(self):
        return False


class _ParentNode:
    def __init__(self, display_node):
        self._display_node = display_node

    def path(self):
        return "/obj/geo1"

    def displayNode(self):
        return self._display_node

    def children(self):
        return [self._display_node]


class _HouStub:
    updateMode = _UpdateMode

    def __init__(self, mode, nodes=None):
        self._mode = mode
        self._nodes = nodes or {}

    def updateModeSetting(self):
        return self._mode

    def node(self, path):
        return self._nodes.get(path)


class GeometryValidationSignalsTest(unittest.TestCase):
    def setUp(self):
        self._old_hou = mcp_client.hou


    def tearDown(self):
        mcp_client.hou = self._old_hou

    
    def _client_for(self, mode, geometry):
        mcp_client.hou = _HouStub(mode)
        client = object.__new__(mcp_client.HoudiniMCP)
        node = _Node(geometry)
        client._resolve_geometry_node = lambda node_path: (node, None)
        client._jsonable_value = lambda value: value
        return client

    def test_manual_empty_geometry_reports_temporary_auto_validation_action(self):
        client = self._client_for(_UpdateMode.Manual, _Geometry())

        ok, result = client.get_geometry_summary(
            "/obj/geo1/OUT",
            max_sample_points=0,
            include_attributes=False,
            include_groups=False,
        )

        self.assertTrue(ok)
        self.assertEqual(result["update_mode"], "Manual")
        self.assertTrue(result["manual_mode"])
        self.assertTrue(result["is_empty_geometry"])
        self.assertEqual(result["recommended_next_action"], "temporary_auto_validate")

    def test_auto_empty_geometry_does_not_recommend_auto_validation(self):
        client = self._client_for(_UpdateMode.Auto, _Geometry())

        ok, result = client.get_geometry_summary(
            "/obj/geo1/OUT",
            max_sample_points=0,
            include_attributes=False,
            include_groups=False,
        )

        self.assertTrue(ok)
        self.assertEqual(result["update_mode"], "Auto")
        self.assertFalse(result["manual_mode"])
        self.assertTrue(result["is_empty_geometry"])
        self.assertNotEqual(result["recommended_next_action"], "temporary_auto_validate")

    def test_manual_nonempty_geometry_is_high_confidence(self):
        client = self._client_for(_UpdateMode.Manual, _Geometry(point_count=8, primitive_count=2, vertex_count=16))

        ok, result = client.get_geometry_summary(
            "/obj/geo1/OUT",
            max_sample_points=0,
            include_attributes=False,
            include_groups=False,
        )

        self.assertTrue(ok)
        self.assertTrue(result["manual_mode"])
        self.assertFalse(result["is_empty_geometry"])
        self.assertEqual(result["validation_confidence"], "high")

    def test_verify_network_tool_returns_structured_manual_empty_signal(self):
        display_node = _Node(_Geometry())
        parent = _ParentNode(display_node)
        mcp_client.hou = _HouStub(_UpdateMode.Manual, {"/obj/geo1": parent})
        client = object.__new__(mcp_client.HoudiniMCP)

        result = client._tool_verify_network({"parent_path": "/obj/geo1"})

        self.assertTrue(result["success"])
        self.assertIn("validation_signal", result)
        self.assertTrue(result["validation_signal"]["manual_mode_detected"])
        self.assertTrue(result["validation_signal"]["display_geometry_empty"])
        self.assertEqual(
            result["validation_signal"]["recommended_next_action"],
            "temporary_auto_validate",
        )


if __name__ == "__main__":
    unittest.main()