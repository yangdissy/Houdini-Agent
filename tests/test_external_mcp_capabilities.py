# -*- coding: utf-8 -*-
"""External MCP manifest and capability contracts."""

import json
from pathlib import Path
import unittest

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs

_install_hou_stub()
_install_thirdparty_stubs()

from houdini_agent.utils.mcp.capabilities import (
    build_external_tool_manifest,
    build_connection_status,
    build_runtime_capabilities,
    render_external_manifest_json,
)
from houdini_agent.utils.tool_registry import ToolRegistry


def _schema(name):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test",
            "parameters": {
                "type": "object",
                "properties": {"node_path": {"type": "string"}},
            },
        },
    }


class ExternalMCPManifestTest(unittest.TestCase):
    def test_manifest_is_stable_bounded_metadata_only(self):
        registry = ToolRegistry()
        registry.register(
            "inspect", _schema("inspect"), modes={"ask"}, runtime="houdini",
            tags={"readonly", "network"}, risk_level="low",
            external_mcp_visible=True,
        )

        manifest = build_external_tool_manifest(
            registry,
            dispatch={"inspect": "_tool_inspect"},
            allowed_tools={"inspect"},
        )

        self.assertEqual(manifest, [{
            "name": "inspect",
            "runtime": "houdini",
            "risk_level": "low",
            "readonly": True,
            "mutating": False,
            "handler": "_tool_inspect",
            "long_running": False,
            "feature": None,
            "minimum_houdini_version": None,
        }])
        serialized = json.dumps(manifest, sort_keys=True)
        self.assertNotIn("node_path", serialized)
        self.assertNotIn("prompt", serialized.lower())

    def test_manifest_excludes_hidden_denied_and_handlerless_tools(self):
        registry = ToolRegistry()
        for name, visible in (("visible", True), ("hidden", False), ("denied", True)):
            registry.register(
                name, _schema(name), modes={"ask"}, runtime="houdini",
                tags={"readonly"}, risk_level="low", external_mcp_visible=visible,
            )

        manifest = build_external_tool_manifest(
            registry,
            dispatch={"visible": "_tool_visible", "denied": "_tool_denied"},
            allowed_tools={"visible", "hidden", "denied"},
            denied_tools={"denied"},
        )

        self.assertEqual([item["name"] for item in manifest], ["visible"])

    def test_committed_manifest_has_no_drift(self):
        from scripts.generate_external_mcp_manifest import generate

        committed = Path("config/external_mcp_manifest.json").read_text(encoding="utf-8")

        self.assertEqual(committed, generate())


class RuntimeCapabilitiesTest(unittest.TestCase):
    def test_healthy_capabilities_report_versions_session_and_tools(self):
        manifest = [{
            "name": "inspect", "handler": "_tool_inspect", "feature": None,
            "minimum_houdini_version": None,
        }]
        dispatcher = type("Dispatcher", (), {"_tool_inspect": lambda self, args: args})()
        executor = type("Executor", (), {
            "is_blocked": lambda self: False,
            "is_shutdown": lambda self: False,
        })()
        hou_stub = type("Hou", (), {
            "applicationVersionString": staticmethod(lambda: "21.0.440")
        })()

        result = build_runtime_capabilities(
            manifest=manifest,
            dispatcher=dispatcher,
            executor=executor,
            hou_module=hou_stub,
            agent_version="1.5.3",
            sdk_version="2.0.0",
            session_id="session-1",
        )

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["houdini_version"], "21.0.440")
        self.assertEqual(result["agent_version"], "1.5.3")
        self.assertEqual(result["mcp_sdk_version"], "2.0.0")
        self.assertEqual(result["session_id"], "session-1")
        self.assertEqual(result["available_tools"], ["inspect"])
        self.assertEqual(result["unavailable_tools"], [])

    def test_capabilities_degrade_without_executing_missing_handler(self):
        manifest = [{
            "name": "missing", "handler": "_tool_missing", "feature": None,
            "minimum_houdini_version": None,
        }]
        executor = type("Executor", (), {
            "is_blocked": lambda self: True,
            "is_shutdown": lambda self: False,
        })()

        result = build_runtime_capabilities(
            manifest=manifest,
            dispatcher=object(),
            executor=executor,
            hou_module=None,
            agent_version="1.5.3",
            sdk_version=None,
            session_id="session-1",
        )

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["executor_state"], "blocked")
        self.assertEqual(result["available_tools"], [])
        self.assertEqual(result["unavailable_tools"], [{
            "name": "missing", "reason": "handler_unavailable",
        }])
        self.assertIn("houdini_unavailable", result["degradations"])
        self.assertIn("mcp_sdk_version_unavailable", result["degradations"])

    def test_tool_degrades_when_houdini_version_is_too_old(self):
        manifest = [{
            "name": "future_tool", "handler": "_tool_future", "feature": None,
            "minimum_houdini_version": "22.0",
        }]
        dispatcher = type("Dispatcher", (), {"_tool_future": lambda self, args: args})()
        executor = type("Executor", (), {
            "is_blocked": lambda self: False,
            "is_shutdown": lambda self: False,
        })()
        hou_stub = type("Hou", (), {
            "applicationVersionString": staticmethod(lambda: "21.0.440")
        })()

        result = build_runtime_capabilities(
            manifest, dispatcher, executor, hou_stub, "1.5.3", "2.0.0", "session-1"
        )

        self.assertEqual(result["available_tools"], [])
        self.assertEqual(result["unavailable_tools"], [{
            "name": "future_tool", "reason": "houdini_version_too_old:22.0",
        }])

    def test_connection_status_classifies_actionable_failures(self):
        cases = (
            (False, None, "not_started"),
            (True, {"degradations": ["mcp_sdk_version_unavailable"]}, "sdk_missing"),
            (True, {"degradations": ["houdini_unavailable"]}, "houdini_unavailable"),
            (True, {"degradations": ["executor_blocked"]}, "executor_blocked"),
            (True, {"degradations": ["tool_capability_mismatch"]}, "capability_missing"),
            (True, {"degradations": []}, "connected"),
        )
        for running, capabilities, expected in cases:
            with self.subTest(expected=expected):
                result = build_connection_status(running, capabilities)
                self.assertEqual(result["state"], expected)
                self.assertEqual(result["running"], running)


if __name__ == "__main__":
    unittest.main()