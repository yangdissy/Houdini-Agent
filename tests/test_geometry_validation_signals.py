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
    AutoUpdate = _ModeValue("AutoUpdate")


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

    def countPrimType(self, primitive_type):
        return 0


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
        self.set_modes = []

    def updateModeSetting(self):
        return self._mode

    def setUpdateMode(self, mode):
        self.set_modes.append(mode)
        self._mode = mode

    def node(self, path):
        return self._nodes.get(path)


class _RestoreFailHouStub(_HouStub):
    def setUpdateMode(self, mode):
        if mode is _UpdateMode.Manual and self.set_modes:
            raise RuntimeError("restore failed")
        super().setUpdateMode(mode)


class _NoAutoUpdateMode:
    Manual = _ModeValue("Manual")


class _NoAutoHouStub(_HouStub):
    updateMode = _NoAutoUpdateMode


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
        client = self._client_for(_UpdateMode.AutoUpdate, _Geometry())

        ok, result = client.get_geometry_summary(
            "/obj/geo1/OUT",
            max_sample_points=0,
            include_attributes=False,
            include_groups=False,
        )

        self.assertTrue(ok)
        self.assertEqual(result["update_mode"], "AutoUpdate")
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

    def test_temporary_auto_validate_geometry_restores_update_mode(self):
        hou_stub = _HouStub(_UpdateMode.Manual)
        mcp_client.hou = hou_stub
        client = object.__new__(mcp_client.HoudiniMCP)
        node = _Node(_Geometry(point_count=4, primitive_count=1, vertex_count=4))
        client._resolve_geometry_node = lambda node_path: (node, None)
        client._jsonable_value = lambda value: value

        result = client._tool_temporary_auto_validate_geometry({
            "node_path": "/obj/geo1/OUT",
            "max_sample_points": 0,
        })

        self.assertTrue(result["success"])
        self.assertTrue(result["temporary_auto_validation"])
        self.assertEqual(result["restored_update_mode"], "Manual")
        self.assertIn("临时 Auto 验证完成", result["summary"])
        self.assertEqual(result["result"]["point_count"], 4)
        self.assertEqual(hou_stub.set_modes, [_UpdateMode.AutoUpdate, _UpdateMode.Manual])
        self.assertEqual(result["health"], "healthy")
        self.assertEqual(result["freshness"]["status"], "fresh")
        self.assertEqual(result["freshness"]["target"], "/obj/geo1/OUT")
        self.assertTrue(result["freshness"]["cook_succeeded"])
        self.assertTrue(result["freshness"]["read_succeeded"])
        self.assertTrue(result["restore_attempted"])
        self.assertTrue(result["restore_succeeded"])

    def test_temporary_auto_validate_geometry_requires_target(self):
        mcp_client.hou = _HouStub(_UpdateMode.Manual)
        client = object.__new__(mcp_client.HoudiniMCP)

        result = client._tool_temporary_auto_validate_geometry({})

        self.assertFalse(result["success"])
        self.assertIn("node_path", result["error"])

    def test_temporary_auto_validation_restore_failure_is_not_healthy(self):
        hou_stub = _RestoreFailHouStub(_UpdateMode.Manual)
        mcp_client.hou = hou_stub
        client = object.__new__(mcp_client.HoudiniMCP)
        node = _Node(_Geometry(point_count=4, primitive_count=1, vertex_count=4))
        client._resolve_geometry_node = lambda node_path: (node, None)
        client._jsonable_value = lambda value: value

        result = client._tool_temporary_auto_validate_geometry({"node_path": "/obj/geo1/OUT"})

        self.assertFalse(result["success"])
        self.assertEqual(result["health"], "unknown")
        self.assertTrue(result["restore_attempted"])
        self.assertFalse(result["restore_succeeded"])
        self.assertNotIn("已恢复", result.get("result", ""))

    def test_temporary_auto_validation_preserves_operation_and_restore_errors(self):
        hou_stub = _RestoreFailHouStub(_UpdateMode.Manual)
        mcp_client.hou = hou_stub
        client = object.__new__(mcp_client.HoudiniMCP)
        node = _Node(_Geometry())
        node.cook = lambda force=False: (_ for _ in ()).throw(RuntimeError("cook failed"))
        client._resolve_geometry_node = lambda node_path: (node, None)

        result = client._tool_temporary_auto_validate_geometry({"node_path": "/obj/geo1/OUT"})

        self.assertFalse(result["success"])
        self.assertIn("cook failed", result["operation_error"])
        self.assertIn("restore failed", result["restore_error"])
        self.assertEqual(result["health"], "unknown")
        self.assertEqual(result["freshness"]["status"], "unknown")

    def test_temporary_auto_validation_fails_closed_without_auto_mode(self):
        node = _Node(_Geometry(point_count=4, primitive_count=1, vertex_count=4))
        mcp_client.hou = _NoAutoHouStub(
            _NoAutoUpdateMode.Manual,
            {"/obj/geo1/OUT": node},
        )
        client = object.__new__(mcp_client.HoudiniMCP)
        client._resolve_geometry_node = lambda node_path: (node, None)
        client._jsonable_value = lambda value: value

        result = client._tool_temporary_auto_validate_geometry({"node_path": "/obj/geo1/OUT"})

        self.assertFalse(result["success"])
        self.assertEqual(result["health"], "unknown")
        self.assertEqual(result["freshness"]["status"], "unknown")
        self.assertEqual(node.cook_calls, [])

    def test_geometry_wrapper_preserves_structured_metadata_for_loop_guard(self):
        client = self._client_for(_UpdateMode.Manual, _Geometry())
        original = client.get_geometry_summary
        client.get_geometry_summary = lambda node_path, **kwargs: (True, {
            "node_path": node_path,
            "point_count": 0,
            "primitive_count": 0,
            "manual_mode": True,
            "is_empty_geometry": True,
            "recommended_next_action": "temporary_auto_validate",
        })

        result = client._tool_get_geometry_summary({"node_path": "/obj/geo1/OUT"})

        self.assertTrue(result["success"])
        self.assertIsInstance(result["result"], str)
        self.assertTrue(result["data"]["manual_mode"])
        self.assertEqual(result["data"]["recommended_next_action"], "temporary_auto_validate")
        self.assertEqual(result["freshness"]["status"], "stale")
        self.assertEqual(result["health"], "unknown")

    def test_set_update_mode_sets_auto_without_restore(self):
        hou_stub = _HouStub(_UpdateMode.Manual)
        mcp_client.hou = hou_stub
        client = object.__new__(mcp_client.HoudiniMCP)

        result = client._tool_set_update_mode({"mode": "auto"})

        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "AutoUpdate")
        self.assertEqual(hou_stub.set_modes, [_UpdateMode.AutoUpdate])
        self.assertEqual(result["data"]["requested"], "auto")
        self.assertEqual(result["data"]["effective"], "AutoUpdate")
        self.assertEqual(result["data"]["mode_kind"], "auto")
        self.assertTrue(result["data"]["persistent"])

    def test_set_update_mode_accepts_auto_update_alias(self):
        hou_stub = _HouStub(_UpdateMode.Manual)
        mcp_client.hou = hou_stub
        client = object.__new__(mcp_client.HoudiniMCP)

        result = client._tool_set_update_mode({"mode": "Auto Update"})

        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "AutoUpdate")
        self.assertEqual(hou_stub.set_modes, [_UpdateMode.AutoUpdate])

    def test_set_update_mode_rejects_unknown_mode(self):
        mcp_client.hou = _HouStub(_UpdateMode.Manual)
        client = object.__new__(mcp_client.HoudiniMCP)

        result = client._tool_set_update_mode({"mode": "sometimes"})

        self.assertFalse(result["success"])
        self.assertIn("mode", result["error"])

    def test_check_errors_manual_mode_validates_only_target_and_restores(self):
        target = _Node(_Geometry(point_count=4, primitive_count=1, vertex_count=4))
        other = _Node(_Geometry())
        hou_stub = _HouStub(_UpdateMode.Manual, {
            "/obj/geo1/OUT": target,
            "/obj/geo2/OUT": other,
        })
        mcp_client.hou = hou_stub
        client = object.__new__(mcp_client.HoudiniMCP)
        client.check_node_errors_text = lambda path: (True, "节点无错误")

        result = client._tool_check_errors({"node_path": "/obj/geo1/OUT"})

        self.assertTrue(result["success"])
        self.assertEqual(result["health"], "healthy")
        self.assertEqual(target.cook_calls, [True])
        self.assertEqual(other.cook_calls, [])
        self.assertEqual(hou_stub.set_modes, [_UpdateMode.AutoUpdate, _UpdateMode.Manual])
        self.assertTrue(result["restore_succeeded"])
        self.assertEqual(result["freshness"]["status"], "fresh")

    def test_check_errors_volume_skip_has_unknown_health(self):
        target = _Node(_Geometry())
        target.needsToCook = lambda: True
        hou_stub = _HouStub(_UpdateMode.Manual, {"/obj/geo1/VDB": target})
        mcp_client.hou = hou_stub
        client = object.__new__(mcp_client.HoudiniMCP)
        client.check_node_errors_text = lambda path: (True, "节点无错误")

        result = client._tool_check_errors({"node_path": "/obj/geo1/VDB"})

        self.assertEqual(result["health"], "unknown")
        self.assertEqual(result["freshness"]["status"], "unknown")
        self.assertTrue(result["validation_blocked"])
        self.assertNotIn("无错误", result["result"])


if __name__ == "__main__":
    unittest.main()