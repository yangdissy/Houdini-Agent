# -*- coding: utf-8 -*-
"""Structured post-write verification for external MCP mutation candidates."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs

_install_hou_stub()
_install_thirdparty_stubs()

from houdini_agent.utils.mcp.client import HoudiniMCP


class _Type:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _Node:
    def __init__(self, path, node_type="box"):
        self._path = path
        self._type = _Type(node_type)
        self._inputs = {}

    def path(self):
        return self._path

    def type(self):
        return self._type

    def input(self, index):
        return self._inputs.get(index)

    def children(self):
        return tuple(getattr(self, "_children", ()))

    def position(self):
        return getattr(self, "_position", (0.0, 0.0))


class ExternalMCPMutationVerificationTest(unittest.TestCase):
    def test_create_nodes_batch_enforces_hard_limits_before_mutation(self):
        client = object.__new__(HoudiniMCP)
        calls = []
        client.create_network = lambda plan: calls.append(plan) or (True, "ok")

        too_many_nodes = HoudiniMCP._tool_create_nodes_batch(client, {
            "nodes": [{"id": str(index), "type": "box"} for index in range(26)],
        })
        too_many_connections = HoudiniMCP._tool_create_nodes_batch(client, {
            "nodes": [{"id": "a", "type": "box"}],
            "connections": [{"from": "a", "to": "a"} for _ in range(51)],
        })
        too_many_parameters = HoudiniMCP._tool_create_nodes_batch(client, {
            "nodes": [{
                "id": "a", "type": "box",
                "parameters": {"p%d" % index: index for index in range(101)},
            }],
        })

        self.assertFalse(too_many_nodes["success"])
        self.assertFalse(too_many_connections["success"])
        self.assertFalse(too_many_parameters["success"])
        self.assertEqual(calls, [])

    def test_create_nodes_batch_returns_bounded_verification(self):
        client = object.__new__(HoudiniMCP)
        parent = _Node("/stage", "lopnet")
        created = [_Node("/stage/node%d" % index, "null") for index in range(2)]

        def create_network(plan):
            parent._children = created
            return True, "ok"

        client.create_network = create_network
        hou = type("Hou", (), {"node": staticmethod(lambda path: parent if path == "/stage" else None)})()

        with patch("houdini_agent.utils.mcp.client.hou", hou):
            result = HoudiniMCP._tool_create_nodes_batch(client, {
                "parent_path": "/stage",
                "nodes": [
                    {"id": "a", "type": "null"},
                    {"id": "b", "type": "null"},
                ],
                "connections": [{"from": "a", "to": "b"}],
            })

        self.assertEqual(result["verification"]["status"], "verified")
        self.assertEqual(result["verification"]["created_paths"], ["/stage/node0", "/stage/node1"])

    def test_create_nodes_batch_plan_hash_guard(self):
        client = object.__new__(HoudiniMCP)
        client.create_network = lambda plan: (True, "ok")

        plan_args = {
            "parent_path": "/stage",
            "nodes": [{"id": "a", "type": "null"}],
            "connections": [],
        }
        dry = HoudiniMCP._tool_create_nodes_batch(client, dict(plan_args, dry_run=True))
        self.assertTrue(dry["success"])
        self.assertIn("plan_hash", dry)

        # 哈希一致 → 放行
        matched = HoudiniMCP._tool_create_nodes_batch(
            client, dict(plan_args, expected_plan=dry["plan_hash"])
        )
        self.assertTrue(matched["success"])

        # 哈希失配 → 零写入拒绝
        calls = []
        client.create_network = lambda plan: calls.append(plan) or (True, "ok")
        mismatched = HoudiniMCP._tool_create_nodes_batch(
            client, dict(plan_args, expected_plan="deadbeefdeadbeef")
        )
        self.assertFalse(mismatched["success"])
        self.assertIn("plan mismatch", mismatched["error"])
        self.assertEqual(calls, [])

    def test_create_node_returns_actual_path_and_type_verification(self):
        client = object.__new__(HoudiniMCP)
        parent = _Node("/obj/project", "geo")
        created = _Node("/obj/project/box1", "box")

        def create_node(*args):
            parent._children = [created]
            return True, "ok"

        client.create_node = create_node
        hou = type("Hou", (), {"node": staticmethod(lambda path: parent if path == parent.path() else None)})()

        with patch("houdini_agent.utils.mcp.client.hou", hou):
            result = HoudiniMCP._tool_create_node(client, {
                "node_type": "box", "parent_path": parent.path(),
            })

        self.assertEqual(result["verification"], {
            "status": "verified",
            "node_path": created.path(),
            "node_type": "box",
            "parent_path": parent.path(),
        })

    def test_set_parameter_returns_actual_value_verification(self):
        client = object.__new__(HoudiniMCP)
        client.set_parameter = lambda *args: (
            True,
            "ok",
            {"old_value": 1, "new_value": 2, "node_path": "/obj/project/box1", "param_name": "scale"},
        )

        result = HoudiniMCP._tool_set_node_parameter(client, {
            "node_path": "/obj/project/box1", "param_name": "scale", "value": 2,
        })

        self.assertEqual(result["verification"], {
            "status": "verified",
            "node_path": "/obj/project/box1",
            "param_name": "scale",
            "actual_value": 2,
        })

    def test_connect_nodes_returns_verified_endpoints(self):
        client = object.__new__(HoudiniMCP)
        source = _Node("/obj/project/source")
        target = _Node("/obj/project/target")
        target._inputs[1] = source
        client.connect_nodes = lambda *args: (True, "ok")
        hou = type("Hou", (), {"node": staticmethod(lambda path: {
            source.path(): source, target.path(): target,
        }.get(path))})()

        with patch("houdini_agent.utils.mcp.client.hou", hou):
            result = HoudiniMCP._tool_connect_nodes(client, {
                "from_path": source.path(), "to_path": target.path(), "input_index": 1,
            })

        self.assertEqual(result["verification"]["status"], "verified")
        self.assertEqual(result["verification"]["input_index"], 1)

    def test_successful_write_with_failed_readback_is_applied_unknown(self):
        client = object.__new__(HoudiniMCP)
        client.connect_nodes = lambda *args: (True, "ok")
        hou = type("Hou", (), {"node": staticmethod(lambda path: None)})()

        with patch("houdini_agent.utils.mcp.client.hou", hou):
            result = HoudiniMCP._tool_connect_nodes(client, {
                "from_path": "/obj/project/source", "to_path": "/obj/project/target",
            })

        self.assertTrue(result["success"])
        self.assertEqual(result["verification"]["status"], "applied_unknown")

    def test_layout_nodes_verification_reads_back_actual_positions(self):
        client = object.__new__(HoudiniMCP)
        node = _Node("/obj/project/source")
        node._position = (9.0, 9.0)
        parent = _Node("/obj/project")
        hou = type("Hou", (), {"node": staticmethod(lambda path: {
            parent.path(): parent, node.path(): node,
        }.get(path))})()

        with patch("houdini_agent.utils.mcp.client.hou", hou), patch(
            "houdini_agent.utils.mcp.hou_core.layout_nodes",
            return_value=(True, "ok", [{
                "name": "source", "path": node.path(), "x": 1.0, "y": 2.0,
            }]),
        ):
            result = HoudiniMCP._tool_layout_nodes(client, {
                "network_path": parent.path(), "node_paths": [node.path()],
            })

        self.assertTrue(result["success"])
        self.assertEqual(result["verification"]["status"], "applied_unknown")
        self.assertEqual(result["verification"]["mismatched_paths"], [node.path()])


if __name__ == "__main__":
    unittest.main()