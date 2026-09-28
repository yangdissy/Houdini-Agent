# -*- coding: utf-8 -*-
"""Generate or verify the committed external MCP capability manifest."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from houdini_agent.utils.mcp.capabilities import (
    build_external_tool_manifest,
    render_external_manifest_json,
)
from houdini_agent.utils.mcp.settings import MCPSettings
from houdini_agent.utils.tool_registry import ToolRegistry


MANIFEST_PATH = REPO_ROOT / "config" / "external_mcp_manifest.json"


def _literal_assignment(path: Path, target_name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == target_name for target in targets):
                return ast.literal_eval(node.value)
    raise RuntimeError(f"Literal assignment not found: {target_name}")


def _literal_class_attribute(path: Path, class_name: str, attribute_name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                targets = item.targets if isinstance(item, ast.Assign) else (
                    [item.target] if isinstance(item, ast.AnnAssign) else []
                )
                if any(isinstance(target, ast.Name) and target.id == attribute_name for target in targets):
                    return ast.literal_eval(item.value)
    raise RuntimeError(f"Literal class attribute not found: {class_name}.{attribute_name}")


def generate() -> str:
    houdini_tools = _literal_assignment(
        REPO_ROOT / "houdini_agent" / "utils" / "ai_client.py", "HOUDINI_TOOLS"
    )
    dispatch = _literal_class_attribute(
        REPO_ROOT / "houdini_agent" / "utils" / "mcp" / "client.py",
        "HoudiniMCP",
        "_TOOL_DISPATCH",
    )
    registry = ToolRegistry()
    registry.register_core_tools(houdini_tools)
    settings = MCPSettings()
    manifest = build_external_tool_manifest(
        registry,
        dispatch=dispatch,
        allowed_tools=settings.allowed_tools,
        denied_tools=settings.denied_tools,
    )
    return render_external_manifest_json(manifest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = generate()
    if args.check:
        if not MANIFEST_PATH.exists() or MANIFEST_PATH.read_text(encoding="utf-8") != expected:
            print("external MCP manifest drift detected")
            return 1
        print("external MCP manifest is current")
        return 0
    MANIFEST_PATH.write_text(expected, encoding="utf-8")
    print(f"wrote {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
