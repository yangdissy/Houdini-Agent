# -*- coding: utf-8 -*-
"""Spare parameter creation and replacement contract tests."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs


_install_hou_stub()
_install_thirdparty_stubs()

import houdini_agent.utils.mcp.client as mcp_client
from houdini_agent.utils.mcp.client import HoudiniMCP


class _Template:
    def __init__(self, name, label, length=1, **kwargs):
        self._name = name
        self.label = label
        self.length = length
        self.kwargs = kwargs

    def name(self):
        return self._name


class _TemplateGroup:
    def __init__(self, templates=None):
        self.templates = list(templates or [])

    def find(self, name):
        return next((template for template in self.templates if template.name() == name), None)

    def append(self, template):
        self.templates.append(template)

    def replace(self, name, template):
        for index, current in enumerate(self.templates):
            if current.name() == name:
                self.templates[index] = template
                return
        raise LookupError(name)


class _Parm:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class _Node:
    def __init__(self, templates=None):
        self.group = _TemplateGroup(templates)
        self.applied = []

    def parmTemplateGroup(self):
        return self.group

    def setParmTemplateGroup(self, group):
        self.group = group
        self.applied.append(group)

    def parm(self, name):
        return _Parm(f"/obj/geo1/CTRL/{name}") if self.group.find(name) else None


class SpareParameterManagementTest(unittest.TestCase):
    def _fake_hou(self, node):
        return type("Hou", (), {
            "node": staticmethod(lambda path: node),
            "FloatParmTemplate": _Template,
            "IntParmTemplate": _Template,
            "StringParmTemplate": _Template,
            "ToggleParmTemplate": _Template,
            "MenuParmTemplate": _Template,
            "parmNamingScheme": type("NamingScheme", (), {
                "XYZW": "XYZW",
                "RGBA": "RGBA",
            }),
        })()

    def test_creates_float_spare_parameter(self):
        node = _Node()
        with patch.object(mcp_client, "hou", self._fake_hou(node)):
            ok, message, data = HoudiniMCP().upsert_spare_parameter(
                "/obj/geo1/CTRL",
                "flower_open",
                "花开",
                "float",
                default=0.0,
                minimum=0.0,
                maximum=1.0,
            )

        self.assertTrue(ok, message)
        self.assertEqual(data["operation"], "created")
        self.assertEqual(data["parameter_path"], "/obj/geo1/CTRL/flower_open")
        template = node.group.find("flower_open")
        self.assertEqual(template.kwargs["default_value"], (0.0,))
        self.assertEqual(template.kwargs["min"], 0.0)
        self.assertEqual(template.kwargs["max"], 1.0)

    def test_rejects_existing_parameter_without_replace(self):
        node = _Node([_Template("flower_open", "Old", 1)])
        with patch.object(mcp_client, "hou", self._fake_hou(node)):
            ok, message, data = HoudiniMCP().upsert_spare_parameter(
                "/obj/geo1/CTRL", "flower_open", "花开", "float"
            )

        self.assertFalse(ok)
        self.assertIn("replace=true", message)
        self.assertIsNone(data)
        self.assertEqual(node.applied, [])

    def test_replaces_existing_parameter_when_explicit(self):
        node = _Node([_Template("flower_open", "Old", 1)])
        with patch.object(mcp_client, "hou", self._fake_hou(node)):
            ok, message, data = HoudiniMCP().upsert_spare_parameter(
                "/obj/geo1/CTRL", "flower_open", "花开", "float", replace=True
            )

        self.assertTrue(ok, message)
        self.assertEqual(data["operation"], "replaced")
        self.assertEqual(node.group.find("flower_open").label, "花开")

    def test_creates_high_frequency_scalar_types(self):
        cases = (
            ("int", 3, "default_value", (3,)),
            ("toggle", True, "default_value", True),
            ("string", "cache.$F4.bgeo.sc", "default_value", ("cache.$F4.bgeo.sc",)),
        )
        for parameter_type, default, key, expected in cases:
            with self.subTest(parameter_type=parameter_type):
                node = _Node()
                with patch.object(mcp_client, "hou", self._fake_hou(node)):
                    ok, message, data = HoudiniMCP().upsert_spare_parameter(
                        "/obj/geo1/CTRL", "control", "Control",
                        parameter_type, default=default,
                    )

                self.assertTrue(ok, message)
                self.assertEqual(node.group.find("control").kwargs[key], expected)
                self.assertEqual(data["parameter_type"], parameter_type)

    def test_creates_menu_parameter(self):
        node = _Node()
        with patch.object(mcp_client, "hou", self._fake_hou(node)):
            ok, message, data = HoudiniMCP().upsert_spare_parameter(
                "/obj/geo1/CTRL", "mode", "Mode", "menu",
                default="fast",
                menu_items=["quality", "fast"],
                menu_labels=["Quality", "Fast"],
            )

        self.assertTrue(ok, message)
        template = node.group.find("mode")
        self.assertEqual(template.kwargs["menu_items"], ("quality", "fast"))
        self.assertEqual(template.kwargs["menu_labels"], ("Quality", "Fast"))
        self.assertEqual(template.kwargs["default_value"], "fast")
        self.assertEqual(data["menu_items"], ["quality", "fast"])

    def test_creates_vector_and_color_parameters(self):
        cases = (
            ("vector2", 2, [1, 2], "XYZW"),
            ("vector3", 3, [1, 2, 3], "XYZW"),
            ("vector4", 4, [1, 2, 3, 4], "XYZW"),
            ("color", 3, [0.1, 0.2, 0.3], "RGBA"),
        )
        for parameter_type, size, default, naming_scheme in cases:
            with self.subTest(parameter_type=parameter_type):
                node = _Node()
                with patch.object(mcp_client, "hou", self._fake_hou(node)):
                    ok, message, data = HoudiniMCP().upsert_spare_parameter(
                        "/obj/geo1/CTRL", "value", "Value",
                        parameter_type, default=default,
                    )

                self.assertTrue(ok, message)
                template = node.group.find("value")
                self.assertEqual(template.length, size)
                self.assertEqual(template.kwargs["default_value"], tuple(default))
                self.assertEqual(template.kwargs["naming_scheme"], naming_scheme)
                self.assertEqual(data["size"], size)

    def test_rejects_invalid_tuple_and_menu_contracts(self):
        node = _Node()
        with patch.object(mcp_client, "hou", self._fake_hou(node)):
            vector_ok, vector_message, _ = HoudiniMCP().upsert_spare_parameter(
                "/obj/geo1/CTRL", "value", "Value", "vector3", default=[1, 2]
            )
            menu_ok, menu_message, _ = HoudiniMCP().upsert_spare_parameter(
                "/obj/geo1/CTRL", "mode", "Mode", "menu",
                menu_items=["a", "b"], menu_labels=["A"],
            )

        self.assertFalse(vector_ok)
        self.assertIn("3", vector_message)
        self.assertFalse(menu_ok)
        self.assertIn("数量", menu_message)


if __name__ == "__main__":
    unittest.main()