# -*- coding: utf-8 -*-
"""Read-only USD prim inspection contract tests."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs


_install_hou_stub()
_install_thirdparty_stubs()

import houdini_agent.utils.mcp.client as mcp_client
from houdini_agent.utils.usd_inspection import inspect_usd_layer_stack, inspect_usd_prim


class _Path:
    def __init__(self, value):
        self.pathString = value

    def __str__(self):
        return self.pathString


class _Attribute:
    def __init__(self, name, value):
        self._name = name
        self._value = value

    def GetName(self):
        return self._name

    def GetTypeName(self):
        return "string"

    def HasAuthoredValueOpinion(self):
        return True

    def Get(self):
        return self._value


class _Layer:
    identifier = "asset.usda"
    realPath = "/show/asset.usda"
    anonymous = False
    dirty = False
    subLayerPaths = ["model.usda", "look.usda"]


class _SessionLayer(_Layer):
    identifier = "session.usda"
    realPath = ""
    anonymous = True
    subLayerPaths = []


class _Spec:
    path = _Path("/World/geo")
    layer = _Layer()


class _Prim:
    def __init__(self):
        self._attributes = [_Attribute("purpose", "render"), _Attribute("huge", "x" * 300000)]

    def IsValid(self):
        return True

    def GetPath(self):
        return _Path("/World/geo")

    def GetTypeName(self):
        return "Mesh"

    def IsActive(self):
        return True

    def IsLoaded(self):
        return True

    def IsDefined(self):
        return True

    def IsInstance(self):
        return False

    def GetAttributes(self):
        return self._attributes

    def GetAllMetadata(self):
        return {"kind": "component", "customData": {"secret": "bounded"}}

    def GetPrimStack(self):
        return [_Spec()]


class _Stage:
    def GetPrimAtPath(self, path):
        return _Prim() if path == "/World/geo" else None

    def GetRootLayer(self):
        return _Layer()

    def GetSessionLayer(self):
        return _SessionLayer()

    def GetLayerStack(self, include_session_layers=True):
        return [_SessionLayer(), _Layer()]

    def GetMutedLayers(self):
        return ["muted.usda"]


class _Material:
    def GetPath(self):
        return _Path("/World/Looks/mat")


class _BindingAPI:
    def __init__(self, prim):
        self.prim = prim

    def ComputeBoundMaterial(self, purpose):
        return _Material(), "bindingRel"


class _UsdShade:
    class Tokens:
        allPurpose = "allPurpose"

    MaterialBindingAPI = _BindingAPI


class _Arc:
    def __init__(self, arc_type, target):
        self.arcType = arc_type
        self.targetNode = target


class _CompositionQuery:
    def __init__(self, prim):
        self.prim = prim

    def GetCompositionArcs(self):
        return [_Arc("Reference", "/World/source"), _Arc("Payload", "/World/cache")]


class _Usd:
    PrimCompositionQuery = _CompositionQuery


class USDInspectionTest(unittest.TestCase):
    def test_prim_info_is_bounded_and_reports_binding_and_stack(self):
        result = inspect_usd_prim(
            _Stage(), "/World/geo", attribute_names=["purpose", "huge", "missing"],
            max_attributes=10, max_metadata=10, payload_limit_bytes=4096,
            usd_shade=_UsdShade, usd_module=_Usd,
        )

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(data["path"], "/World/geo")
        self.assertEqual(data["type"], "Mesh")
        self.assertEqual(data["attributes"][0]["name"], "purpose")
        self.assertEqual(data["missing_attributes"], ["missing"])
        self.assertTrue(data["truncated"])
        self.assertLessEqual(data["payload_bytes"], data["payload_limit_bytes"])
        self.assertEqual(data["prim_stack"][0]["layer"], "asset.usda")
        self.assertEqual(data["composition_arcs"][0]["type"], "Reference")
        self.assertEqual(data["material_binding"]["material_path"], "/World/Looks/mat")

    def test_layer_stack_reports_root_session_sublayers_and_muted_layers(self):
        result = inspect_usd_layer_stack(_Stage(), max_layers=10, max_sublayers=10)

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(data["root_layer"]["identifier"], "asset.usda")
        self.assertEqual(data["session_layer"]["identifier"], "session.usda")
        self.assertEqual(data["muted_layers"], ["muted.usda"])
        self.assertEqual(data["layers"][1]["sub_layers"], ["model.usda", "look.usda"])
        self.assertFalse(data["truncated"])

    def test_missing_prim_and_missing_pxr_are_structured(self):
        missing = inspect_usd_prim(_Stage(), "/missing", usd_shade=_UsdShade)
        self.assertFalse(missing["success"])
        self.assertEqual(missing["error_code"], "prim_not_found")

        with patch("houdini_agent.utils.usd_inspection._load_usd_shade", return_value=None):
            unavailable = inspect_usd_prim(_Stage(), "/World/geo")
        self.assertFalse(unavailable["success"])
        self.assertEqual(unavailable["error_code"], "pxr_unavailable")


class USDPrimToolHandlerTest(unittest.TestCase):
    def setUp(self):
        self.old_hou = mcp_client.hou

    def tearDown(self):
        mcp_client.hou = self.old_hou

    def test_handler_reads_lop_stage_and_returns_structured_data(self):
        stage = _Stage()
        node = type("LopNode", (), {"stage": lambda self: stage})()
        mcp_client.hou = type("Hou", (), {"node": lambda self, path: node})()
        client = object.__new__(mcp_client.HoudiniMCP)

        with patch(
            "houdini_agent.utils.usd_inspection._load_usd_shade", return_value=_UsdShade
        ):
            result = client._tool_get_usd_prim_info({
                "node_path": "/stage/OUT",
                "prim_path": "/World/geo",
                "attribute_names": ["purpose"],
            })

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["path"], "/World/geo")
        self.assertEqual(result["data"]["material_binding"]["material_path"], "/World/Looks/mat")

    def test_handler_rejects_missing_lop_node(self):
        mcp_client.hou = type("Hou", (), {"node": lambda self, path: None})()
        client = object.__new__(mcp_client.HoudiniMCP)

        result = client._tool_get_usd_prim_info({
            "node_path": "/stage/missing", "prim_path": "/World"
        })

        self.assertFalse(result["success"])
        self.assertIn("/stage/missing", result["error"])

    def test_layer_stack_handler_reads_same_lop_stage(self):
        stage = _Stage()
        node = type("LopNode", (), {"stage": lambda self: stage})()
        mcp_client.hou = type("Hou", (), {"node": lambda self, path: node})()
        client = object.__new__(mcp_client.HoudiniMCP)

        result = client._tool_get_usd_layer_stack({"node_path": "/stage/OUT"})

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["muted_layers"], ["muted.usda"])
        self.assertEqual(result["data"]["layer_count"], 2)


if __name__ == "__main__":
    unittest.main()