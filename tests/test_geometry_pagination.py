# -*- coding: utf-8 -*-
"""Bounded geometry pagination contract tests."""

import unittest

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs


_install_hou_stub()
_install_thirdparty_stubs()

import houdini_agent.utils.mcp.client as mcp_client


class _Attrib:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _Element:
    def __init__(self, number, values, element_type="Polygon"):
        self._number = number
        self._values = values
        self._type = element_type

    def number(self):
        return self._number

    def attribValue(self, attrib):
        return self._values[attrib.name()]

    def type(self):
        return type("PrimType", (), {"name": lambda self: "Polygon"})()


class _Group:
    def __init__(self, elements):
        self._elements = elements

    def iterPoints(self):
        return iter(self._elements)

    def iterPrims(self):
        return iter(self._elements)


class _Geometry:
    def __init__(self):
        self.points = [_Element(i, {"P": (float(i), 0.0, 0.0), "Cd": (1.0, 0.0, 0.0)}) for i in range(6)]
        self.prims = [_Element(i, {"name": f"piece_{i}"}) for i in range(4)]

    def pointAttribs(self):
        return [_Attrib("P"), _Attrib("Cd")]

    def primAttribs(self):
        return [_Attrib("name")]

    def iterPoints(self):
        return iter(self.points)

    def iterPrims(self):
        return iter(self.prims)

    def findPointGroup(self, name):
        return _Group(self.points[1:5]) if name == "middle" else None

    def findPrimGroup(self, name):
        return _Group(self.prims[1:]) if name == "render" else None


class _Node:
    def __init__(self, geometry):
        self._geometry = geometry

    def path(self):
        return "/obj/geo1/OUT"

    def geometry(self, output_index=0):
        if output_index != 1:
            raise RuntimeError("wrong output")
        return self._geometry


class GeometryPaginationTest(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(mcp_client.HoudiniMCP)
        self.geometry = _Geometry()
        self.node = _Node(self.geometry)
        self.client._resolve_geometry_node = lambda node_path: (self.node, None)
        self.client._jsonable_value = lambda value: value

    def test_points_are_filtered_and_paginated(self):
        ok, result = self.client.get_geometry_elements(
            node_path="/obj/geo1/OUT",
            element_type="point",
            attributes=["P", "missing"],
            start=1,
            count=2,
            group="middle",
            output_index=1,
        )

        self.assertTrue(ok)
        self.assertEqual(result["elements"], [
            {"number": 2, "P": (2.0, 0.0, 0.0)},
            {"number": 3, "P": (3.0, 0.0, 0.0)},
        ])
        self.assertEqual(result["missing_attributes"], ["missing"])
        self.assertEqual(result["total_count"], 4)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["next_start"], 3)

    def test_primitives_include_type_and_finish_page(self):
        ok, result = self.client.get_geometry_elements(
            node_path="/obj/geo1/OUT",
            element_type="primitive",
            attributes=["name"],
            start=1,
            count=10,
            group="render",
            output_index=1,
        )

        self.assertTrue(ok)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["elements"][0], {
            "number": 2, "type": "Polygon", "name": "piece_2"
        })
        self.assertFalse(result["truncated"])
        self.assertIsNone(result["next_start"])

    def test_count_is_hard_limited_and_invalid_group_fails(self):
        ok, result = self.client.get_geometry_elements(
            "/obj/geo1/OUT", "point", start=-5, count=100000, output_index=1
        )

        self.assertTrue(ok)
        self.assertEqual(result["start"], 0)
        self.assertEqual(result["requested_count"], 100000)
        self.assertEqual(result["page_limit"], 500)

        ok, result = self.client.get_geometry_elements(
            "/obj/geo1/OUT", "point", group="missing", output_index=1
        )
        self.assertFalse(ok)
        self.assertIn("group", result["error"].lower())

    def test_payload_size_stops_before_next_large_element(self):
        self.geometry.points = [
            _Element(0, {"P": (0.0, 0.0, 0.0), "Cd": "x" * 140000}),
            _Element(1, {"P": (1.0, 0.0, 0.0), "Cd": "y" * 140000}),
        ]

        ok, result = self.client.get_geometry_elements(
            "/obj/geo1/OUT", "point", attributes=["Cd"], count=2, output_index=1
        )

        self.assertTrue(ok)
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["next_start"], 1)
        self.assertLessEqual(result["payload_bytes"], result["payload_limit_bytes"])


if __name__ == "__main__":
    unittest.main()