from __future__ import print_function

import argparse
import json
import os
from pathlib import Path
import sys
import traceback

import hou

from houdini_agent.core.houdini_main_thread_executor import HoudiniMainThreadExecutor
from houdini_agent.utils.ai_client import HOUDINI_TOOLS
from houdini_agent.utils.mcp.client import HoudiniMCP
from houdini_agent.utils.tool_registry import get_tool_registry


def _write_result(path, scenario, status, checks=None, error=""):
    payload = {
        "schema_version": 1,
        "scenario": scenario,
        "status": status,
        "houdini_version": hou.applicationVersionString(),
        "python_version": sys.version.split()[0],
        "scene_path": hou.hipFile.path(),
        "checks": checks or {},
    }
    if error:
        payload["error"] = error
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _runtime():
    registry = get_tool_registry()
    if not registry.initialized:
        registry.register_core_tools(HOUDINI_TOOLS)
    client = object.__new__(HoudiniMCP)
    executor = HoudiniMainThreadExecutor(
        emit_tool_request=lambda name, kwargs: None,
        emit_batch_request=lambda batch: None,
        result_queue=None,
    )
    return client, executor


def _run(executor, client, tool_name, args):
    return executor.run_in_main_thread(
        tool_name=tool_name,
        kwargs=args,
        execute_tool=lambda name, kwargs: client.execute_tool(name, kwargs),
        cook_before_read=lambda: None,
        snapshot_network_children=lambda: {},
        diff_network_children=lambda before, after: None,
        refresh_selection_baseline=lambda: None,
        self_tracking_tools=frozenset(),
        error_formatter=str,
    )


def mutation_undo(test_root):
    client, executor = _runtime()
    project = hou.node("/obj").createNode("geo", "isolated_mutation")
    create = _run(executor, client, "create_node", {
        "node_type": "box",
        "node_name": "box1",
        "parent_path": project.path(),
    })
    if not create.get("success"):
        raise AssertionError("create_node failed: %r" % create)
    box_path = create.get("verification", {}).get("node_path")
    if not box_path or hou.node(box_path) is None:
        raise AssertionError("created node was not found")
    set_parm = _run(executor, client, "set_node_parameter", {
        "node_path": box_path,
        "param_name": "scale",
        "value": 2.0,
    })
    if not set_parm.get("success") or hou.node(box_path).parm("scale").eval() != 2.0:
        raise AssertionError("set_node_parameter failed: %r" % set_parm)
    null = project.createNode("null", "OUT")
    connect = _run(executor, client, "connect_nodes", {
        "from_path": box_path,
        "to_path": null.path(),
        "input_index": 0,
        "output_index": 0,
    })
    if not connect.get("success") or null.input(0) != hou.node(box_path):
        raise AssertionError("connect_nodes failed: %r" % connect)
    hou.undos.performUndo()
    if null.input(0) is not None:
        raise AssertionError("one undo did not restore the connection")
    return {
        "create": True,
        "set_parameter": True,
        "connect": True,
        "undo": True,
    }


def update_mode_restore(test_root):
    client, executor = _runtime()
    project = hou.node("/obj").createNode("geo", "isolated_update_mode")
    first_node = project.createNode("box", "manual_guard")
    hou.setUpdateMode(hou.updateMode.AutoUpdate)
    first = _run(executor, client, "set_node_parameter", {
        "node_path": first_node.path(), "param_name": "scale", "value": 2.0,
    })
    if not first.get("success") or hou.updateModeSetting() != hou.updateMode.Manual:
        raise AssertionError("default mutation guard did not enter Manual")
    hou.setUpdateMode(hou.updateMode.AutoUpdate)
    executor.set_explicit_update_mode("auto")
    second = _run(executor, client, "set_node_parameter", {
        "node_path": first_node.path(), "param_name": "scale", "value": 3.0,
    })
    if not second.get("success") or hou.updateModeSetting() != hou.updateMode.AutoUpdate:
        raise AssertionError("explicit Auto intent was not preserved")
    return {"default_manual": True, "explicit_auto": True}


def hip_save_reload(test_root):
    client, executor = _runtime()
    project = hou.node("/obj").createNode("geo", "isolated_saved_geo")
    box = project.createNode("box", "saved_box")
    box.parm("scale").set(3.0)
    hip_path = (Path(test_root) / "hip" / "isolated_save.hip").resolve()
    result = _run(executor, client, "save_hip", {"file_path": str(hip_path)})
    if not result.get("success") or not hip_path.is_file():
        raise AssertionError("save_hip failed: %r" % result)
    hou.hipFile.clear(suppress_save_prompt=True)
    hou.hipFile.load(str(hip_path), suppress_save_prompt=True)
    loaded = hou.node("/obj/isolated_saved_geo/saved_box")
    if loaded is None or loaded.parm("scale").eval() != 3.0:
        raise AssertionError("saved HIP did not restore the test fixture")
    return {"saved": True, "reloaded": True, "path_in_test_root": True}


def schema_handler_contract(test_root):
    client, executor = _runtime()
    registry = get_tool_registry()
    schemas = {
        item["function"]["name"]: item
        for item in HOUDINI_TOOLS
        if isinstance(item, dict) and isinstance(item.get("function"), dict)
    }
    names = (
        "create_node", "set_node_parameter", "connect_nodes",
        "save_hip", "undo_redo", "set_update_mode",
    )
    for name in names:
        if name not in schemas:
            raise AssertionError("missing schema: %s" % name)
        handler_name = HoudiniMCP._TOOL_DISPATCH.get(name)
        if not handler_name or not callable(getattr(HoudiniMCP, handler_name, None)):
            raise AssertionError("missing dispatch handler: %s" % name)
        meta = registry.get_meta(name)
        if meta is None or meta.runtime != "houdini":
            raise AssertionError("invalid registry metadata: %s" % name)
    project = hou.node("/obj").createNode("geo", "isolated_contract")
    result = _run(executor, client, "create_node", {
        "node_type": "null", "node_name": "dispatch_proof", "parent_path": project.path(),
    })
    if not result.get("success") or hou.node(project.path() + "/dispatch_proof") is None:
        raise AssertionError("formal execute_tool dispatch failed: %r" % result)
    return {"schema_count": len(names), "dispatch_execution": True}


def failure_recovery(test_root):
    client, executor = _runtime()
    project = hou.node("/obj").createNode("geo", "isolated_failure")
    original = HoudiniMCP._TOOL_DISPATCH["create_node"]

    def failing_handler(self, args):
        project.createNode("null", "partial_change")
        raise RuntimeError("controlled integration failure")

    setattr(HoudiniMCP, "_tool_controlled_failure", failing_handler)
    HoudiniMCP._TOOL_DISPATCH["create_node"] = "_tool_controlled_failure"
    try:
        failed = _run(executor, client, "create_node", {
            "node_type": "null", "node_name": "ignored", "parent_path": project.path(),
        })
    finally:
        HoudiniMCP._TOOL_DISPATCH["create_node"] = original
        delattr(HoudiniMCP, "_tool_controlled_failure")
    if failed.get("success"):
        raise AssertionError("controlled handler failure reported success")
    if executor.is_blocked():
        raise AssertionError("ordinary handler exception blocked the executor")
    hou.undos.performUndo()
    if project.node("partial_change") is not None:
        raise AssertionError("undo did not remove the partial change")
    recovered = _run(executor, client, "create_node", {
        "node_type": "null", "node_name": "after_failure", "parent_path": project.path(),
    })
    if not recovered.get("success") or project.node("after_failure") is None:
        raise AssertionError("executor did not recover after handler failure: %r" % recovered)
    return {"failure_reported": True, "undo_recovered": True, "next_call_succeeded": True}


def package_hda_isolation(test_root):
    package_marker = os.environ.get("HOUDINI_TEST_PACKAGE_MARKER")
    if package_marker != "isolated-package-loaded":
        raise AssertionError("temporary Houdini package was not loaded")
    hda_path = (Path(test_root) / "artifacts" / "isolated_asset.hda").resolve()
    subnet = hou.node("/obj").createNode("subnet", "isolated_asset_source")
    asset = subnet.createDigitalAsset(
        name="houdini_agent_test::isolated_asset::1.0",
        hda_file_name=str(hda_path),
        description="Houdini Agent Isolated Test Asset",
    )
    if not hda_path.is_file() or not hou.hda.definitionsInFile(str(hda_path)):
        raise AssertionError("temporary HDA was not created")
    asset.destroy()
    hou.hda.uninstallFile(str(hda_path))
    hou.hda.installFile(str(hda_path))
    definitions = hou.hda.definitionsInFile(str(hda_path))
    if not definitions:
        raise AssertionError("temporary HDA could not be reinstalled")
    instance = hou.node("/obj").createNode(definitions[0].nodeTypeName(), "isolated_asset_instance")
    if instance is None:
        raise AssertionError("temporary HDA instance was not created")
    instance.destroy()
    hou.hda.uninstallFile(str(hda_path))
    return {"package_loaded": True, "hda_lifecycle": True, "path_in_test_root": True}


SCENARIOS = {
    "mutation_undo": mutation_undo,
    "update_mode_restore": update_mode_restore,
    "hip_save_reload": hip_save_reload,
    "schema_handler_contract": schema_handler_contract,
    "failure_recovery": failure_recovery,
    "package_hda_isolation": package_hda_isolation,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    test_root = Path(os.environ["HOUDINI_TEST_ROOT"]).resolve()
    result_path = Path(args.result).resolve()
    if test_root not in result_path.parents:
        raise SystemExit("result path must be inside the test root")
    previous_mode = hou.updateModeSetting()
    try:
        hou.hipFile.clear(suppress_save_prompt=True)
        checks = SCENARIOS[args.scenario](test_root)
        _write_result(result_path, args.scenario, "passed", checks=checks)
        return 0
    except Exception as exc:
        _write_result(
            result_path,
            args.scenario,
            "failed",
            error="%s\n%s" % (exc, traceback.format_exc()),
        )
        return 1
    finally:
        try:
            hou.setUpdateMode(previous_mode)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
