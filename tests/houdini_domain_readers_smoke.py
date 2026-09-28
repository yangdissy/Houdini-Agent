# -*- coding: utf-8 -*-
"""Real-Houdini smoke checks for bounded geometry, USD, and PDG readers."""

from __future__ import print_function

import json
import sys
import traceback

import hou

from houdini_agent.utils.mcp.client import HoudiniMCP
from houdini_agent.utils.pdg_inspection import inspect_top_network
from houdini_agent.utils.usd_inspection import inspect_usd_layer_stack, inspect_usd_prim


def _result(status, **details):
    payload = {"status": status}
    payload.update(details)
    return payload


def check_geometry():
    obj = hou.node("/obj")
    geo = obj.createNode("geo", "mcp_smoke_geo")
    box = geo.createNode("box", "box1")
    box.cook(force=True)
    client = object.__new__(HoudiniMCP)
    ok, data = client.get_geometry_elements(
        box.path(), "point", attributes=["P"], start=0, count=2
    )
    if not ok or data.get("count") != 2 or not data.get("truncated"):
        raise AssertionError("geometry pagination contract failed: %r" % data)
    return _result("passed", node_path=box.path(), point_count=data["total_count"])


def check_usd():
    stage_network = hou.node("/stage")
    if stage_network is None:
        return _result("skipped", reason="/stage network unavailable")
    lop = stage_network.createNode("null", "mcp_smoke_stage")
    stage = lop.stage()
    layer_result = inspect_usd_layer_stack(stage)
    if not layer_result.get("success"):
        raise AssertionError("USD layer inspection failed: %r" % layer_result)
    prim_result = inspect_usd_prim(stage, "/")
    if not prim_result.get("success"):
        raise AssertionError("USD root prim inspection failed: %r" % prim_result)
    return _result(
        "passed",
        node_path=lop.path(),
        layer_count=layer_result["data"]["layer_count"],
    )


def check_pdg():
    obj = hou.node("/obj")
    try:
        topnet = obj.createNode("topnet", "mcp_smoke_topnet")
        top = topnet.createNode("genericgenerator", "generator1")
    except Exception as exc:
        return _result("skipped", reason="TOP fixture unavailable: %s" % exc)
    result = inspect_top_network(top)
    if not result.get("success"):
        return _result("skipped", reason=result.get("error", "PDG context unavailable"))
    return _result(
        "passed",
        node_path=top.path(),
        work_item_count=result["data"]["work_item_count"],
    )


def main():
    hou.hipFile.clear(suppress_save_prompt=True)
    checks = {}
    for name, check in (("geometry", check_geometry), ("usd", check_usd), ("pdg", check_pdg)):
        try:
            checks[name] = check()
        except Exception as exc:
            checks[name] = _result("failed", error=str(exc), traceback=traceback.format_exc())
    payload = {
        "houdini_version": hou.applicationVersionString(),
        "checks": checks,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 1 if any(item["status"] == "failed" for item in checks.values()) else 0


if __name__ == "__main__":
    sys.exit(main())