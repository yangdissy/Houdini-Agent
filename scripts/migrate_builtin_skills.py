# -*- coding: utf-8 -*-
"""Migrate literal built-in SKILL_INFO modules to standard Skill bundles."""

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, Tuple


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "houdini_agent" / "skills"
DESCRIPTOR_FIELDS = {
    "name", "description", "category", "risk_level", "parameters",
}


def _read_skill(path: Path) -> Tuple[Dict[str, Any], str]:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))
    assignment = None
    metadata = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "SKILL_INFO" for target in node.targets):
            assignment = node
            metadata = ast.literal_eval(node.value)
            break
    if assignment is None or not isinstance(metadata, dict):
        raise ValueError(f"{path}: SKILL_INFO must be one literal dictionary assignment")

    lines = source.splitlines(keepends=True)
    del lines[assignment.lineno - 1:assignment.end_lineno]
    entrypoint = re.sub(
        r"^from \.(\_[A-Za-z0-9_]+) import ",
        rf"from houdini_agent.skills.{path.parent.name}.\1 import ",
        "".join(lines),
        flags=re.MULTILINE,
    )
    entrypoint = re.sub(
        r"^from \.\.(\_[A-Za-z0-9_]+) import ",
        r"from houdini_agent.skills.\1 import ",
        entrypoint,
        flags=re.MULTILINE,
    )
    return metadata, entrypoint


def migrate(path: Path) -> Path:
    metadata, entrypoint = _read_skill(path)
    name = metadata.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{path}: SKILL_INFO.name must be a non-empty string")
    bundle = path.parent / name
    if bundle.exists():
        raise FileExistsError(f"Refusing to overwrite existing bundle: {bundle}")

    descriptor = {
        key: value for key, value in metadata.items()
        if key in DESCRIPTOR_FIELDS
    }
    descriptor["entrypoint"] = "scripts/main.py:run"
    scripts = bundle / "scripts"
    scripts.mkdir(parents=True)
    (bundle / "SKILL.md").write_text(
        "---\n"
        + json.dumps(descriptor, ensure_ascii=False, separators=(",", ":"))
        + "\n---\n# "
        + name.replace("_", " ").title()
        + "\n\n按照参数合同执行此 Skill；保持返回结构与既有行为不变。\n",
        encoding="utf-8",
    )
    (scripts / "main.py").write_text(entrypoint, encoding="utf-8")
    path.unlink()
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    for value in args.paths:
        source = (SKILLS_ROOT / value).resolve()
        if SKILLS_ROOT.resolve() not in source.parents or source.suffix != ".py":
            raise ValueError(f"Invalid built-in Skill path: {value}")
        print(migrate(source).relative_to(ROOT))


if __name__ == "__main__":
    main()
