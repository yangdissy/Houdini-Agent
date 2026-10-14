# -*- coding: utf-8 -*-
"""Preview, install, or activate a reviewed user Skill."""

import ast
import json
import os
import shutil
from pathlib import Path

from houdini_agent.skills._contract import validate_metadata




MAX_SOURCE_BYTES = 256 * 1024
DESCRIPTOR_FIELDS = {
    "name", "description", "category", "risk_level", "parameters", "entrypoint",
}


def _error(message, action="preview"):
    return {
        "error": message, "action": action, "mode": action,
        "installed": False, "active": False, "executed": False,
    }


def _configured_user_dir():
    from houdini_agent import skills
    return skills._get_user_skill_dir()


def _literal_dict(node):
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None
    return value if isinstance(value, dict) else None


def _validate_source(skill_source):
    if len(skill_source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return None, f"Skill source exceeds {MAX_SOURCE_BYTES} bytes."
    try:
        tree = ast.parse(skill_source)
    except SyntaxError as exc:
        return None, f"Skill source has invalid Python syntax: line {exc.lineno}: {exc.msg}"

    metadata = None
    run_node = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            run_node = node
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "SKILL_INFO" for target in node.targets):
                metadata = _literal_dict(node.value)
    if metadata is None:
        return None, "SKILL_INFO must be a literal dictionary."
    if run_node is None or isinstance(run_node, ast.AsyncFunctionDef):
        return None, "Skill must define a synchronous run() function."

    metadata_error = validate_metadata(metadata)
    if metadata_error:
        return None, metadata_error
    name = metadata["name"]
    category = metadata["category"]
    description = metadata["description"]
    risk_level = metadata["risk_level"]
    parameters = metadata["parameters"]

    lowered = skill_source.lower()
    if '"status": "draft"' in lowered or "'status': 'draft'" in lowered:
        return None, "Draft placeholder source cannot be installed."
    if "implementation required before this skill can be installed" in lowered:
        return None, "Draft placeholder source cannot be installed."
    return {
        "name": name,
        "category": category,
        "description": description,
        "risk_level": risk_level,
        "parameters": sorted(parameters),
    }, None


def _validate_bundle(skill_files):
    if not isinstance(skill_files, dict):
        return None, "'skill_files' must contain SKILL.md and scripts/main.py."
    if set(skill_files) != {"SKILL.md", "scripts/main.py"}:
        return None, "Bundle must contain exactly SKILL.md and scripts/main.py."
    if not all(isinstance(value, str) for value in skill_files.values()):
        return None, "Bundle file contents must be strings."
    if sum(len(value.encode("utf-8")) for value in skill_files.values()) > MAX_SOURCE_BYTES:
        return None, f"Skill bundle exceeds {MAX_SOURCE_BYTES} bytes."

    markdown = skill_files["SKILL.md"]
    if not markdown.startswith("---\n"):
        return None, "SKILL.md must start with JSON frontmatter between --- markers."
    marker = markdown.find("\n---\n", 4)
    if marker < 0:
        return None, "SKILL.md frontmatter is not closed."
    try:
        metadata = json.loads(markdown[4:marker])
    except (TypeError, ValueError) as exc:
        return None, f"SKILL.md frontmatter is invalid JSON: {exc}"
    unknown = sorted(set(metadata) - DESCRIPTOR_FIELDS)
    if unknown:
        return None, f"Unknown SKILL.md frontmatter fields: {', '.join(unknown)}"
    metadata_error = validate_metadata(metadata)
    if metadata_error:
        return None, metadata_error
    if metadata.get("entrypoint") != "scripts/main.py:run":
        return None, "Bundle entrypoint must be scripts/main.py:run."

    source = skill_files["scripts/main.py"]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return None, f"Skill entrypoint has invalid Python syntax: line {exc.lineno}: {exc.msg}"
    run_node = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run"),
        None,
    )
    if run_node is None:
        return None, "Skill entrypoint must define a synchronous run() function."
    lowered = source.lower()
    if '"status": "draft"' in lowered or "'status': 'draft'" in lowered:
        return None, "Draft placeholder source cannot be installed."
    if "implementation required before this skill can be installed" in lowered:
        return None, "Draft placeholder source cannot be installed."
    return {
        "name": metadata["name"], "category": metadata["category"],
        "description": metadata["description"], "risk_level": metadata["risk_level"],
        "parameters": sorted(metadata["parameters"]),
    }, None


def _target_path(user_dir, name):
    root = Path(user_dir).resolve()
    if root.is_symlink():
        return None, "Configured user Skill directory cannot be a symbolic link."
    target = root / name
    if target.exists() and target.is_symlink():
        return None, "Target Skill file cannot be a symbolic link."
    try:
        target.resolve().relative_to(root)
    except ValueError:
        return None, "Target path escapes the configured user Skill directory."
    return target, None


def _builtin_skill_exists(name):
    from houdini_agent import skills
    skills._load_all()
    source = skills._registry_sources.get(name)
    return source is not None and not source["source"].startswith("user_")


def _write_atomic(target, skill_files):
    partial = target.with_name(target.name + ".partial")
    try:
        partial.mkdir()
        for relative_path, source in skill_files.items():
            destination = partial / Path(relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(source)
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(str(partial), str(target))
    finally:
        shutil.rmtree(str(partial), ignore_errors=True)


def _activate(name):
    from houdini_agent import skills
    skills.set_user_skill_active(name, True)
    try:
        skills.reload_skills()
        if not any(item.get("name") == name for item in skills.list_skills()):
            raise RuntimeError("Skill loader did not register the activated Skill.")
    except Exception:
        skills.set_user_skill_active(name, False)
        skills.reload_skills()
        raise


def run(skill_source="", skill_files=None, mode="preview", action=None, skill_name=""):
    """Validate/install source without import, or explicitly activate an installed Skill."""
    action = str(action or mode or "preview").strip().lower()
    if action not in {"preview", "install", "activate"}:
        return _error("'action' must be 'preview', 'install', or 'activate'.", action)

    if action == "activate":
        name = str(skill_name or "").strip()
        if not name or not name.isidentifier() or name.lower() != name:
            return _error("'skill_name' must be a lowercase Python identifier.", action)
        user_dir = _configured_user_dir()
        if user_dir is None:
            return _error("No active user Skill directory is available.", action)
        target, path_error = _target_path(user_dir, name)
        if path_error:
            return _error(path_error, action)
        if not (target / "SKILL.md").is_file():
            return _error(f"Installed user Skill does not exist: {name}", action)
        try:
            _activate(name)
        except Exception as exc:
            return _error(f"Skill activation failed; source was retained but remains inactive: {exc}", action)
        return {
            "action": action, "mode": action, "skill_name": name,
            "target_path": str(target), "installed": True, "active": True, "executed": False,
        }

    if skill_files is None:
        return _error("Standard installation requires 'skill_files'.", action)
    metadata, validation_error = _validate_bundle(skill_files)
    if validation_error:
        return _error(validation_error, action)

    user_dir = _configured_user_dir()
    if user_dir is None:
        return _error(
            "No active user Skill directory is available. Reopen Houdini-Agent to initialize "
            "cache/users/<username>/config.ini [skills] user_skill_dir.", action
        )
    target, path_error = _target_path(user_dir, metadata["name"])
    if path_error:
        return _error(path_error, action)
    if _builtin_skill_exists(metadata["name"]) or target.exists():
        return _error(f"Skill already exists and will not be overwritten: {metadata['name']}", action)

    result = {
        "action": action,
        "mode": action,
        "skill": metadata,
        "target_path": str(target),
        "source_bytes": sum(len(value.encode("utf-8")) for value in skill_files.values()),
        "checks": {
            "syntax_valid": True,
            "metadata_valid": True,
            "target_within_user_dir": True,
            "name_available": True,
            "draft_placeholder_absent": True,
        },
        "installed": False,
        "active": False,
        "executed": False,
    }
    if action == "preview":
        result["next_action"] = "Call again with mode='install' to write this Skill."
        return result

    try:
        _write_atomic(target, skill_files)
    except Exception as exc:
        try:
            shutil.rmtree(str(target))
        except OSError:
            pass
        return _error(f"Skill installation failed: {exc}", action)

    result["installed"] = True
    result["next_action"] = (
        "Call again with action='activate' and skill_name set to explicitly authorize import."
    )
    return result