# -*- coding: utf-8 -*-
"""Tests for the governed external MCP execution adapter."""

import unittest
import threading

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs

_install_hou_stub()
_install_thirdparty_stubs()

from houdini_agent.core.harness_engine import ToolPolicyDecision
from houdini_agent.utils.mcp.external_adapter import ExternalMCPContext, ExternalMCPExecutionAdapter
from houdini_agent.utils.mcp.settings import MCPSettings
from houdini_agent.utils.tool_registry import ToolRegistry


def _schema(name):
    return {"type": "function", "function": {"name": name, "description": "test", "parameters": {}}}


class _Policy:
    def __init__(self, decision):
        self.decision = decision

    def decide(self, *args):
        return self.decision


class ExternalMCPExecutionAdapterTest(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(
            "inspect",
            _schema("inspect"),
            modes={"ask"},
            runtime="houdini",
            risk_level="low",
            tags={"readonly"},
            requires_confirmation=False,
        )
        self.settings = MCPSettings(enabled=True, allowed_tools=("inspect",))
        self.context = ExternalMCPContext(
            session_id="session-1",
            client_id="client-1",
            mode="ask",
            username="artist",
            correlation_id="call-1",
        )

    def _adapter(self, decision=None, execute=None, audit=None, confirm=None, executor=None):
        return ExternalMCPExecutionAdapter(
            settings=self.settings,
            registry=self.registry,
            policy_engine=_Policy(decision or ToolPolicyDecision(action="allow")),
            execute=execute or (lambda name, args: {"success": True, "result": args}),
            audit=audit,
            confirm=confirm,
            executor=executor,
        )

    def test_allow_executes_and_audits_without_argument_values(self):
        calls = []
        audits = []
        adapter = self._adapter(
            execute=lambda name, args: calls.append((name, args)) or {"success": True, "result": "ok"},
            audit=audits.append,
        )

        result = adapter.execute(self.context, "inspect", {"node_path": "/obj/secret"})

        self.assertTrue(result["success"])
        self.assertEqual(calls, [("inspect", {"node_path": "/obj/secret"})])
        self.assertTrue(all(record["correlation_id"] == "call-1" for record in audits))
        self.assertNotIn("/obj/secret", str(audits))

    def test_untrusted_context_allowlist_and_registry_fail_closed(self):
        calls = []
        adapter = self._adapter(execute=lambda *args: calls.append(args))

        invalid = ExternalMCPContext("", "client-1", "ask", "artist", "call-1")
        self.assertFalse(adapter.execute(invalid, "inspect", {})["success"])
        self.assertFalse(adapter.execute(self.context, "execute_python", {})["success"])
        self.registry.set_enabled("inspect", False)
        self.assertFalse(adapter.execute(self.context, "inspect", {})["success"])
        self.assertEqual(calls, [])

    def test_confirmation_unavailable_and_policy_error_fail_closed(self):
        asking = self._adapter(decision=ToolPolicyDecision(action="ask"))
        self.assertFalse(asking.execute(self.context, "inspect", {})["success"])

        class BrokenPolicy:
            def decide(self, *args):
                raise RuntimeError("policy internals")

        adapter = ExternalMCPExecutionAdapter(
            settings=self.settings,
            registry=self.registry,
            policy_engine=BrokenPolicy(),
            execute=lambda *args: {"success": True},
        )
        result = adapter.execute(self.context, "inspect", {})
        self.assertFalse(result["success"])
        self.assertNotIn("internals", result["error"])

    def test_mutating_tool_always_requires_confirmation(self):
        self.registry.register(
            "mutate",
            _schema("mutate"),
            modes={"agent"},
            runtime="houdini",
            risk_level="normal",
            mutating=True,
            requires_confirmation=True,
        )
        self.settings.allowed_tools = ("inspect", "mutate")
        self.settings.max_risk_level = "normal"
        self.settings.max_calls_per_session = 10
        context = ExternalMCPContext("session-1", "client-1", "agent", "artist", "call-2")
        calls = []

        unavailable = self._adapter(execute=lambda *args: calls.append(args) or {"success": True})
        self.assertFalse(unavailable.execute(context, "mutate", {"node_path": "/obj"})["success"])

        denied = self._adapter(
            execute=lambda *args: calls.append(args) or {"success": True},
            confirm=lambda *args: False,
        )
        self.assertFalse(denied.execute(context, "mutate", {"node_path": "/obj"})["success"])

        confirmations = []
        allowed = self._adapter(
            execute=lambda name, args: calls.append((name, args)) or {"success": True},
            confirm=lambda name, args: confirmations.append((name, args)) or True,
        )
        allowed_result = allowed.execute(context, "mutate", {"node_path": "/obj"})
        self.assertTrue(allowed_result["success"], allowed_result)
        self.assertEqual(confirmations, [("mutate", {"node_path": "/obj"})])
        self.assertEqual(calls, [("mutate", {"node_path": "/obj"})])

    def test_mutating_node_paths_require_explicit_write_root(self):
        self.registry.register(
            "mutate",
            _schema("mutate"),
            modes={"agent"},
            runtime="houdini",
            risk_level="normal",
            mutating=True,
            requires_confirmation=True,
            path_kinds={"from_path": "node", "to_path": "node"},
        )
        self.settings.allowed_tools = ("mutate",)
        self.settings.max_risk_level = "normal"
        context = ExternalMCPContext("session-1", "client-1", "agent", "artist", "call-3")
        calls = []
        adapter = self._adapter(
            execute=lambda name, args: calls.append(args) or {"success": True},
            confirm=lambda *args: True,
        )

        no_root = adapter.execute(context, "mutate", {
            "from_path": "/obj/project/a", "to_path": "/obj/project/b",
        })
        self.assertFalse(no_root["success"])
        self.assertEqual(calls, [])

        self.settings.write_node_roots = ("/obj/project",)
        allowed = adapter.execute(context, "mutate", {
            "from_path": "/obj/project/a", "to_path": "/obj/project/sub/b",
        })
        self.assertTrue(allowed["success"])

        escaped = adapter.execute(context, "mutate", {
            "from_path": "/obj/project/a", "to_path": "/obj/project2/b",
        })
        self.assertFalse(escaped["success"])
        self.assertEqual(len(calls), 1)

    def test_external_create_node_requires_explicit_parent_path(self):
        self.registry.register(
            "create_node",
            _schema("create_node"),
            modes={"agent"},
            runtime="houdini",
            risk_level="normal",
            mutating=True,
            requires_confirmation=True,
            path_kinds={"parent_path": "node"},
        )
        self.settings.allowed_tools = ("create_node",)
        self.settings.max_risk_level = "normal"
        self.settings.write_node_roots = ("/obj/project",)
        context = ExternalMCPContext("session-1", "client-1", "agent", "artist", "call-4")
        calls = []
        adapter = self._adapter(
            execute=lambda name, args: calls.append(args) or {"success": True},
            confirm=lambda *args: True,
        )

        result = adapter.execute(context, "create_node", {"node_type": "box"})

        self.assertFalse(result["success"])
        self.assertIn("parent_path", result["error"])
        self.assertEqual(calls, [])

    def test_external_node_modifications_use_per_tool_boundaries(self):
        for name, path_kinds in (
            ("rename_node", {"node_path": "node"}),
            ("layout_nodes", {"network_path": "node"}),
            ("set_node_flags", {"node_path": "node"}),
        ):
            self.registry.register(
                name, _schema(name), modes={"agent"}, runtime="houdini",
                risk_level="normal", mutating=True, requires_confirmation=True,
                path_kinds=path_kinds,
            )
        self.settings.allowed_tools = ("rename_node", "layout_nodes", "set_node_flags")
        self.settings.max_risk_level = "normal"
        self.settings.write_node_roots = ("/obj/project",)
        context = ExternalMCPContext("session-1", "client-1", "agent", "artist", "call-5")
        calls = []
        adapter = self._adapter(
            execute=lambda name, args: calls.append((name, args)) or {"success": True},
            confirm=lambda *args: True,
        )

        self.assertTrue(adapter.execute(context, "rename_node", {
            "node_path": "/obj/project/old", "new_name": "renamed",
        })["success"])
        self.assertFalse(adapter.execute(context, "rename_node", {
            "node_path": "/obj/project/old", "new_name": "../escape",
        })["success"])
        self.assertFalse(adapter.execute(context, "layout_nodes", {
            "network_path": "/obj/project",
        })["success"])
        self.assertTrue(adapter.execute(context, "layout_nodes", {
            "network_path": "/obj/project",
            "node_paths": ["/obj/project/a", "/obj/project/b"],
        })["success"])
        self.assertTrue(adapter.execute(context, "set_node_flags", {
            "node_path": "/obj/project/a", "bypass": True,
        })["success"])
        self.assertFalse(adapter.execute(context, "set_node_flags", {
            "node_path": "/obj/project/a", "display": True,
        })["success"])
        self.assertEqual([name for name, _ in calls], [
            "rename_node", "layout_nodes", "set_node_flags",
        ])

    def test_retry_executes_only_patched_arguments(self):
        calls = []
        adapter = self._adapter(decision=ToolPolicyDecision(
            action="retry", patched_args={"node_path": "/obj/safe"}, retry_key="inspect-safe"
        ), execute=lambda name, args: calls.append(args) or {"success": True})

        result = adapter.execute(self.context, "inspect", {"node_path": "/obj/unsafe"})

        self.assertTrue(result["success"])
        self.assertEqual(calls, [{"node_path": "/obj/safe"}])

    def test_session_call_limit_rejects_before_handler(self):
        calls = []
        settings = MCPSettings(
            enabled=True, allowed_tools=("inspect",), max_calls_per_session=1
        )
        adapter = ExternalMCPExecutionAdapter(
            settings=settings,
            registry=self.registry,
            policy_engine=_Policy(ToolPolicyDecision(action="allow")),
            execute=lambda *args: calls.append(args) or {"success": True},
        )

        self.assertTrue(adapter.execute(self.context, "inspect", {})["success"])
        second = adapter.execute(self.context, "inspect", {})

        self.assertFalse(second["success"])
        self.assertIn("limit", second["error"].lower())
        self.assertEqual(len(calls), 1)

    def test_concurrency_limit_rejects_without_waiting(self):
        calls = []
        settings = MCPSettings(
            enabled=True, allowed_tools=("inspect",), max_concurrent_calls=1
        )
        adapter = ExternalMCPExecutionAdapter(
            settings=settings,
            registry=self.registry,
            policy_engine=_Policy(ToolPolicyDecision(action="allow")),
            execute=lambda *args: calls.append(args) or {"success": True},
        )
        self.assertTrue(adapter._concurrency.acquire(blocking=False))
        try:
            result = adapter.execute(self.context, "inspect", {})
        finally:
            adapter._concurrency.release()

        self.assertFalse(result["success"])
        self.assertIn("concurrency", result["error"].lower())
        self.assertEqual(calls, [])

    def test_long_running_limit_uses_manifest_classification(self):
        calls = []
        settings = MCPSettings(
            enabled=True, allowed_tools=("inspect",), max_long_running_calls=1
        )
        adapter = ExternalMCPExecutionAdapter(
            settings=settings,
            registry=self.registry,
            policy_engine=_Policy(ToolPolicyDecision(action="allow")),
            execute=lambda *args: calls.append(args) or {"success": True},
            manifest=[{"name": "inspect", "long_running": True}],
        )
        self.assertTrue(adapter._long_running.acquire(blocking=False))
        try:
            result = adapter.execute(self.context, "inspect", {})
        finally:
            adapter._long_running.release()

        self.assertFalse(result["success"])
        self.assertIn("long-running", result["error"].lower())
        self.assertEqual(calls, [])

    def test_shutdown_rejects_new_calls_before_handler(self):
        calls = []
        audits = []
        adapter = self._adapter(
            execute=lambda *args: calls.append(args) or {"success": True},
            audit=audits.append,
        )

        adapter.shutdown()
        result = adapter.execute(self.context, "inspect", {})

        self.assertTrue(adapter.is_shutdown())
        self.assertFalse(result["success"])
        self.assertIn("stopped", result["error"].lower())
        self.assertEqual(calls, [])
        self.assertEqual(audits[-1]["reason_code"], "adapter_stopped")

    def test_shutdown_does_not_cancel_started_call_and_rejects_followups(self):
        started = threading.Event()
        release = threading.Event()
        results = []

        def execute(*args):
            started.set()
            release.wait(timeout=1.0)
            return {"success": True, "result": "finished"}

        adapter = self._adapter(execute=execute)
        worker = threading.Thread(
            target=lambda: results.append(adapter.execute(self.context, "inspect", {}))
        )
        worker.start()
        self.assertTrue(started.wait(timeout=1.0))

        adapter.shutdown()
        followup = adapter.execute(self.context, "inspect", {})
        release.set()
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertTrue(results[0]["success"])
        self.assertFalse(followup["success"])
        self.assertIn("stopped", followup["error"].lower())

    def test_executor_blocked_or_shutdown_rejects_before_handler(self):
        for state in ("blocked", "shutdown"):
            with self.subTest(state=state):
                calls = []
                executor = type("Executor", (), {
                    "is_blocked": lambda self: state == "blocked",
                    "is_shutdown": lambda self: state == "shutdown",
                })()
                adapter = self._adapter(
                    execute=lambda *args: calls.append(args) or {"success": True},
                    executor=executor,
                )

                result = adapter.execute(self.context, "inspect", {})

                self.assertFalse(result["success"])
                self.assertIn(state, result["error"].lower())
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()