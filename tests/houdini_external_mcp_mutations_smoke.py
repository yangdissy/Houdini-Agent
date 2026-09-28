# -*- coding: utf-8 -*-
"""Real-Houdini smoke checks for governed external MCP mutation candidates."""

from __future__ import print_function

import json
import sys
import traceback

import hou

from houdini_agent.core.houdini_main_thread_executor import HoudiniMainThreadExecutor
from houdini_agent.utils.ai_client import HOUDINI_TOOLS
from houdini_agent.utils.mcp.client import HoudiniMCP
from houdini_agent.utils.tool_registry import get_tool_registry


def _result(status, **details):
    payload = {"status": status}
    payload.update(details)
    return payload


def _run(executor, client, tool_name, args):
    return executor.run_in_main_thread(
        tool_name=tool_name,
        kwargs=args,
        execute_tool=lambda name, kwargs: getattr(client, "_tool_" + name)(kwargs),
        cook_before_read=lambda: None,
        snapshot_network_children=lambda: {},
        diff_network_children=lambda before, after: None,
        refresh_selection_baseline=lambda: None,
        self_tracking_tools=frozenset(),
        error_formatter=str,
    )


def check_mutations(explicit_auto=False):
    registry = get_tool_registry()
    if not registry.initialized:
        registry.register_core_tools(HOUDINI_TOOLS)
    obj = hou.node("/obj")
    project = obj.createNode("geo", "external_mcp_write_smoke")
    client = object.__new__(HoudiniMCP)
    executor = HoudiniMainThreadExecutor(
        emit_tool_request=lambda name, kwargs: None,
        emit_batch_request=lambda batch: None,
        result_queue=None,
    )
    if explicit_auto:
        executor.set_explicit_update_mode("auto")

    create = _run(executor, client, "create_node", {
        "node_type": "box",
        "node_name": "box1",
        "parent_path": project.path(),
    })
    if not create.get("success") or create.get("verification", {}).get("status") != "verified":
        raise AssertionError("create verification failed: %r" % create)
    box_path = create["verification"]["node_path"]

    set_parm = _run(executor, client, "set_node_parameter", {
        "node_path": box_path,
        "param_name": "scale",
        "value": 2.0,
    })
    if not set_parm.get("success") or set_parm.get("verification", {}).get("actual_value") != 2.0:
        raise AssertionError("parameter verification failed: %r" % set_parm)

    null = project.createNode("null", "OUT")
    connect = _run(executor, client, "connect_nodes", {
        "from_path": box_path,
        "to_path": null.path(),
        "input_index": 0,
        "output_index": 0,
    })
    if not connect.get("success") or connect.get("verification", {}).get("status") != "verified":
        raise AssertionError("connection verification failed: %r" % connect)

    hou.undos.performUndo()
    if null.input(0) is not None:
        raise AssertionError("connect_nodes undo did not restore the previous input state")

    expected_mode = hou.updateMode.AutoUpdate if explicit_auto else hou.updateMode.Manual
    if hou.updateModeSetting() != expected_mode:
        raise AssertionError("mutating executor update mode guard mismatch")

    return _result(
        "passed",
        parent_path=project.path(),
        created_path=box_path,
        parameter_value=set_parm["verification"]["actual_value"],
        connected_to=connect["verification"]["to_path"],
        undo="passed",
        update_mode="auto" if explicit_auto else "manual",
    )


def check_batch_mutation():
    registry = get_tool_registry()
    if not registry.initialized:
        registry.register_core_tools(HOUDINI_TOOLS)
    stage = hou.node("/stage")
    before_paths = {child.path() for child in stage.children()}
    client = object.__new__(HoudiniMCP)
    executor = HoudiniMainThreadExecutor(
        emit_tool_request=lambda name, kwargs: None,
        emit_batch_request=lambda batch: None,
        result_queue=None,
    )
    result = _run(executor, client, "create_nodes_batch", {
        "parent_path": "/stage",
        "nodes": [
            {"id": "a", "type": "null", "name": "mcp_batch_a"},
            {"id": "b", "type": "null", "name": "mcp_batch_b"},
        ],
        "connections": [{"from": "a", "to": "b", "input": 0}],
    })
    if not result.get("success") or result.get("verification", {}).get("status") != "verified":
        raise AssertionError("batch verification failed: %r" % result)
    hou.undos.performUndo()
    after_undo = {child.path() for child in stage.children()}
    single_undo_atomic = after_undo == before_paths
    for path in sorted(after_undo - before_paths, reverse=True):
        node = hou.node(path)
        if node is not None:
            node.destroy()
    return _result(
        "passed",
        created_count=2,
        single_undo_atomic=single_undo_atomic,
        external_visible=False,
        parent_path="/stage",
    )


def check_node_modifications():
    registry = get_tool_registry()
    if not registry.initialized:
        registry.register_core_tools(HOUDINI_TOOLS)
    obj = hou.node("/obj")
    geo = obj.createNode("geo", "external_mcp_modify_smoke")
    first = geo.createNode("box", "old_name")
    second = geo.createNode("null", "second")
    untouched = geo.createNode("null", "untouched")
    untouched_position = tuple(untouched.position())
    display_before = bool(first.isDisplayFlagSet())
    render_before = bool(first.isRenderFlagSet())
    client = object.__new__(HoudiniMCP)
    executor = HoudiniMainThreadExecutor(
        emit_tool_request=lambda name, kwargs: None,
        emit_batch_request=lambda batch: None,
        result_queue=None,
    )

    rename = _run(executor, client, "rename_node", {
        "node_path": first.path(), "new_name": "renamed_box",
    })
    first = hou.node(geo.path() + "/renamed_box")
    if not rename.get("success") or rename.get("verification", {}).get("status") != "verified":
        raise AssertionError("rename verification failed: %r" % rename)

    layout = _run(executor, client, "layout_nodes", {
        "network_path": geo.path(),
        "node_paths": [first.path(), second.path()],
        "method": "grid",
    })
    if not layout.get("success") or layout.get("verification", {}).get("node_count") != 2:
        raise AssertionError("layout verification failed: %r" % layout)
    if tuple(untouched.position()) != untouched_position:
        raise AssertionError("subset layout moved an unlisted node")

    flags = _run(executor, client, "set_node_flags", {
        "node_path": first.path(), "bypass": True,
    })
    if not flags.get("success") or flags.get("verification", {}).get("status") != "verified":
        raise AssertionError("flags verification failed: %r" % flags)
    if bool(first.isDisplayFlagSet()) != display_before or bool(first.isRenderFlagSet()) != render_before:
        raise AssertionError("restricted flags changed display/render state")

    return _result(
        "passed",
        renamed_path=first.path(),
        layout_count=layout["verification"]["node_count"],
        bypass=flags["verification"]["flags"]["bypass"],
        display_unchanged=True,
        render_unchanged=True,
    )


def main():
    hou.hipFile.clear(suppress_save_prompt=True)
    previous_mode = hou.updateModeSetting()
    try:
        hou.setUpdateMode(hou.updateMode.AutoUpdate)
        manual_check = check_mutations(explicit_auto=False)
        hou.hipFile.clear(suppress_save_prompt=True)
        hou.setUpdateMode(hou.updateMode.AutoUpdate)
        auto_check = check_mutations(explicit_auto=True)
        hou.hipFile.clear(suppress_save_prompt=True)
        batch_check = check_batch_mutation()
        hou.hipFile.clear(suppress_save_prompt=True)
        modify_check = check_node_modifications()
        check = _result(
            "passed", manual=manual_check, auto=auto_check,
            batch=batch_check, modifications=modify_check,
        )
    except Exception as exc:
        check = _result("failed", error=str(exc), traceback=traceback.format_exc())
    finally:
        try:
            hou.setUpdateMode(previous_mode)
        except Exception:
            pass
    payload = {
        "houdini_version": hou.applicationVersionString(),
        "check": check,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 1 if check["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())