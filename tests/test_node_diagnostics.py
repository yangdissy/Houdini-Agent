# -*- coding: utf-8 -*-
"""Structured Houdini node diagnostics contracts."""

import unittest

from tests.test_import_smoke import _install_thirdparty_stubs


_install_thirdparty_stubs()

import houdini_agent.utils.mcp.client as mcp_client


class _Category:
    def name(self):
        return "Dop"


class _NodeType:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name

    def category(self):
        return _Category()


class _Template:
    def label(self):
        return "Snippet"

    def type(self):
        return _NodeType("String")

    def defaultValue(self):
        return ("",)

    def isHidden(self):
        return False

    def menuItems(self):
        return ()


class _Parm:
    def __init__(self, value="", locked=False, disabled=False):
        self._value = value
        self._locked = locked
        self._disabled = disabled

    def eval(self):
        return self._value

    def isLocked(self):
        return self._locked

    def isDisabled(self):
        return self._disabled

    def isTimeDependent(self):
        return False


class _ParmTuple:
    def __init__(self, name, parm):
        self._name = name
        self._parm = parm

    def name(self):
        return self._name

    def parmTemplate(self):
        return _Template()

    def eval(self):
        return (self._parm.eval(),)

    def __len__(self):
        return 1


class _Node:
    def __init__(self, path, type_name, parent=None, inside_locked_hda=False, errors=None):
        self._path = path
        self._type = _NodeType(type_name)
        self._parent = parent
        self._inside_locked_hda = inside_locked_hda
        self._errors = list(errors or [])
        self._children = []
        self._parms = {}
        if parent is not None:
            parent._children.append(self)

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def type(self):
        return self._type

    def parent(self):
        return self._parent

    def children(self):
        return self._children

    def allSubChildren(self):
        result = []
        for child in self._children:
            result.append(child)
            result.extend(child.allSubChildren())
        return result

    def errors(self):
        return self._errors

    def warnings(self):
        return []

    def isInsideLockedHDA(self):
        return self._inside_locked_hda

    def isEditableInsideLockedHDA(self):
        return not self._inside_locked_hda

    def isEditable(self):
        return not self._inside_locked_hda

    def parm(self, name):
        return self._parms.get(name)

    def parmTuple(self, name):
        parm = self._parms.get(name)
        return _ParmTuple(name, parm) if parm is not None else None

    def parmTuples(self):
        return [_ParmTuple(name, parm) for name, parm in self._parms.items()]


class _Hou:
    def __init__(self, nodes):
        self._nodes = {node.path(): node for node in nodes}

    def node(self, path):
        return self._nodes.get(path)


class NodeDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self._old_hou = mcp_client.hou
        self.client = object.__new__(mcp_client.HoudiniMCP)

    def tearDown(self):
        mcp_client.hou = self._old_hou

    def test_locked_hda_parameter_contract_and_write_fail_fast(self):
        owner = _Node("/obj/FX/dopnet1/popwrangle1", "popwrangle")
        internal = _Node(
            owner.path() + "/geometrywrangle1/geometryvop1",
            "geometryvop",
            parent=owner,
            inside_locked_hda=True,
        )
        internal._parms["vexscript"] = _Parm("generated code")
        mcp_client.hou = _Hou([owner, internal])

        ok, schema = self.client.get_parameter_schema(internal.path())
        result = self.client._tool_set_node_parameter({
            "node_path": internal.path(),
            "param_name": "vexscript",
            "value": "changed",
        })

        self.assertTrue(ok)
        self.assertFalse(schema["editability"]["writable"])
        self.assertEqual(schema["editability"]["nearest_editable_ancestor"], owner.path())
        self.assertFalse(schema["parameters"][0]["writable"])
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "node_inside_locked_hda")
        self.assertEqual(result["data"]["nearest_editable_ancestor"], owner.path())

    def test_pop_wrangle_compile_error_maps_to_public_snippet_and_deduplicates(self):
        network = _Node("/obj/FX/dopnet1", "dopnet")
        owner = _Node(network.path() + "/popwrangle1", "popwrangle", parent=network)
        owner._parms["snippet"] = _Parm("bad vex")
        internal = _Node(
            owner.path() + "/geometrywrangle1/geometryvop1",
            "geometryvop",
            parent=owner,
            inside_locked_hda=True,
        )
        internal._parms["vex_cwdpath"] = _Parm(owner.path())
        compile_error = (
            "flipobject1 - " + internal.path()
            + ": snippet1: No matching function for matrix3 rotate(float; vector). (49,22:27)"
        )
        first = _Node(network.path() + "/flipobject1", "flipobject", parent=network, errors=[compile_error])
        second = _Node(network.path() + "/flipsolver1", "flipsolver", parent=network, errors=[compile_error])
        mcp_client.hou = _Hou([network, owner, internal, first, second])

        ok, report = self.client.check_node_errors(network.path())

        self.assertTrue(ok)
        self.assertEqual(report["error_count"], 2)
        self.assertEqual(report["root_cause_count"], 1)
        cause = report["root_causes"][0]
        self.assertEqual(cause["reported_node"], internal.path())
        self.assertEqual(cause["owner_node"], owner.path())
        self.assertEqual(cause["repair_parameter"], "snippet")
        self.assertEqual(cause["line"], 49)
        self.assertEqual(cause["columns"], [22, 27])
        self.assertTrue(cause["inside_locked_hda"])
        self.assertEqual(cause["occurrences"], 2)
        self.assertEqual(
            [entry["classification"] for entry in report["errors"]],
            ["root_cause", "propagated_error"],
        )


if __name__ == "__main__":
    unittest.main()