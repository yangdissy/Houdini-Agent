# -*- coding: utf-8 -*-
"""Deterministic, read-only workflow guide lookup."""

import hashlib
import json
import re
import string
import zipfile
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[5]
_DOC_DIR = _REPO_ROOT / "Doc"
_GUIDE_DIR = _DOC_DIR / "workflow_guides"
_NODE_CATALOG_DIR = _DOC_DIR / "node_catalog"
_MIGRATION_MATRIX = _DOC_DIR / "workflow_guide_migration_matrix.md"
_ALIASES = {
    "smoke": "pyro",
    "fire": "pyro",
    "explosion": "pyro",
    "flip": "fluid",
    "liquid": "fluid",
    "water": "fluid",
    "whitewater": "fluid",
    "cloth": "vellum",
    "softbody": "vellum",
    "rbd": "destruction",
    "fracture": "destruction",
    "bullet": "destruction",
    "sand": "mpm",
    "snow": "mpm",
}
_SAFE_TOPIC = re.compile(r"^[a-z][a-z0-9_]*$")
_ALLOWED_PLACEHOLDERS = {"description", "topic"}
_ALLOWED_EVIDENCE = {"local-knowledge", "packaged-help", "runtime-search"}


def _available_topics():
    return sorted(path.stem for path in _GUIDE_DIR.glob("*.md") if path.is_file())


def _resolve_topic(topic):
    key = str(topic or "").strip().lower().replace("/", "")
    if not key or not _SAFE_TOPIC.fullmatch(key):
        return None, "Topic must contain only letters, numbers, and underscores."

    exact = _GUIDE_DIR / f"{key}.md"
    if exact.is_file():
        return key, None

    resolved = _ALIASES.get(key, key)
    candidate = _GUIDE_DIR / f"{resolved}.md"
    if candidate.is_file():
        return resolved, None

    available = ", ".join(_available_topics()) or "(none)"
    return None, (
        f"No workflow guide for '{topic}'. Available topics: {available}. "
        "Use search_houdini_help for subjects without a guide."
    )


def _render(text, values):
    fields = {
        name
        for _, name, _, _ in string.Formatter().parse(text)
        if name
    }
    unknown = sorted(fields - _ALLOWED_PLACEHOLDERS)
    if unknown:
        raise ValueError(f"Unsupported guide placeholders: {', '.join(unknown)}")
    rendered = text.format(**values)
    leftovers = sorted(set(re.findall(r"\{[a-z_]+\}", rendered)))
    if leftovers:
        raise ValueError(f"Unrendered guide placeholders: {', '.join(leftovers)}")
    return rendered


def _help_scopes(text):
    return sorted(set(re.findall(r"`([a-z_]+/[a-z0-9_/-]+\.txt)`", text)))


def _evidence_strategy(text):
    matches = re.findall(r"<!--\s*evidence:\s*([^>]*?)\s*-->", text)
    if len(matches) != 1:
        return None
    strategy = matches[0].strip()
    return strategy if strategy in _ALLOWED_EVIDENCE else None


def _node_references(text):
    return sorted({item["reference"] for item in _node_requirements(text)})


def _version_tuple(version):
    parts = str(version).split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Invalid Houdini version: {version}")
    return tuple(int(part) for part in parts)


def _node_requirements(text):
    matches = re.findall(r"<!--\s*nodes:\s*([^>]+?)\s*-->", text)
    requirements = []
    for declaration in matches:
        for item in declaration.split(","):
            item = item.strip()
            if not item:
                continue
            match = re.fullmatch(
                r"([a-z][a-z0-9_]*/[a-zA-Z0-9_.:-]+)(?:\s+\[(\d+\.\d+\.\d+)(\+)?\])?",
                item,
            )
            if not match:
                raise ValueError(f"Invalid node requirement: {item}")
            reference, version, minimum = match.groups()
            requirements.append({
                "reference": reference,
                "version": version,
                "minimum_version": bool(minimum),
            })
    return sorted(requirements, key=lambda item: (
        item["reference"], item["version"] or "", item["minimum_version"]
    ))


def _node_applies_to(requirement, version):
    required = requirement["version"]
    if required is None:
        return True
    if requirement["minimum_version"]:
        return _version_tuple(version) >= _version_tuple(required)
    return version == required


def _tool_references(text):
    matches = re.findall(r"<!--\s*tools:\s*([^>]*?)\s*-->", text)
    return sorted({
        reference.strip()
        for match in matches
        for reference in match.split(",")
        if reference.strip()
    })


def _source_references(text):
    matches = re.findall(r"<!--\s*sources:\s*([^>]*?)\s*-->", text)
    return sorted({
        reference.strip().replace("\\", "/")
        for match in matches
        for reference in match.split(",")
        if reference.strip()
    })


def _source_exists(reference):
    if not reference.startswith("Doc/"):
        return False
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    return (_REPO_ROOT / relative).exists()


def audit_guides(available_tools, help_page_exists):
    """Audit packaged guide references against callable tools and offline help."""
    known_tools = set(available_tools)
    errors = []
    audited = []
    for source in sorted(_GUIDE_DIR.glob("*.md")):
        text = source.read_text(encoding="utf-8")
        tools = _tool_references(text)
        scopes = _help_scopes(text)
        evidence = _evidence_strategy(text)
        sources = _source_references(text)
        missing_tools = sorted(tool for tool in tools if tool not in known_tools)
        missing_help = sorted(scope for scope in scopes if not help_page_exists(scope))
        missing_sources = sorted(source for source in sources if not _source_exists(source))
        evidence_error = None
        if evidence is None:
            evidence_error = "Guide must declare one supported evidence strategy."
        elif evidence == "packaged-help" and not scopes:
            evidence_error = "packaged-help requires at least one exact help scope."
        elif evidence == "local-knowledge" and not sources:
            evidence_error = "local-knowledge requires at least one source path."
        if missing_tools or missing_help or missing_sources or evidence_error:
            errors.append({
                "guide_id": source.stem,
                "missing_tools": missing_tools,
                "missing_help_scopes": missing_help,
                "missing_sources": missing_sources,
                "evidence_error": evidence_error,
            })
        audited.append(source.stem)
    return {"ok": not errors, "audited_guides": audited, "errors": errors}


def audit_runtime_assets(houdini_versions):
    """Check assets required by the directory-distributed extension."""
    required_files = [
        _DOC_DIR / "nodes.zip",
        _DOC_DIR / "vex.zip",
        _DOC_DIR / "hom.zip",
        _MIGRATION_MATRIX,
    ]
    required_files.extend(
        _NODE_CATALOG_DIR / f"houdini_node_catalog-{version}.json"
        for version in houdini_versions
    )
    missing = [path for path in required_files if not path.is_file() or path.stat().st_size == 0]
    guides = sorted(_GUIDE_DIR.glob("*.md")) if _GUIDE_DIR.is_dir() else []
    if len(guides) != 31:
        missing.append(_GUIDE_DIR)
    return {
        "ok": not missing,
        "missing_assets": [
            path.relative_to(_REPO_ROOT).as_posix()
            for path in missing
        ],
        "guide_count": len(guides),
    }


def audit_packaged_guides(houdini_versions):
    """Audit guides against packaged Doc help and versioned node catalogs."""
    help_entries = set()
    try:
        for archive in ("nodes.zip", "vex.zip", "hom.zip"):
            with zipfile.ZipFile(_DOC_DIR / archive) as help_zip:
                help_entries.update(help_zip.namelist())
    except (FileNotFoundError, zipfile.BadZipFile) as exc:
        return {"ok": False, "error_code": "workflow_guide_evidence_unavailable",
                "error": str(exc), "errors": []}

    catalogs = {}
    try:
        for version in houdini_versions:
            path = _NODE_CATALOG_DIR / f"houdini_node_catalog-{version}.json"
            catalog = json.loads(path.read_text(encoding="utf-8"))
            if catalog.get("houdini_version_string") != version:
                raise ValueError(f"Node catalog version mismatch: {path}")
            catalogs[version] = {
                f"{node['category']}/{node['type_name']}"
                for node in catalog.get("nodes", [])
            }
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return {"ok": False, "error_code": "workflow_guide_evidence_unavailable",
                "error": str(exc), "errors": []}

    errors = []
    for source in sorted(_GUIDE_DIR.glob("*.md")):
        text = source.read_text(encoding="utf-8")
        evidence = _evidence_strategy(text)
        missing_help = sorted(scope for scope in _help_scopes(text) if scope not in help_entries)
        try:
            node_requirements = _node_requirements(text)
            node_error = None
        except ValueError as exc:
            node_requirements = []
            node_error = str(exc)
        missing_nodes = {
            version: sorted(
                requirement["reference"]
                for requirement in node_requirements
                if _node_applies_to(requirement, version)
                and requirement["reference"] not in nodes
            )
            for version, nodes in catalogs.items()
        }
        missing_nodes = {version: refs for version, refs in missing_nodes.items() if refs}
        evidence_error = None
        if evidence is None:
            evidence_error = "Guide must declare one supported evidence strategy."
        elif evidence == "packaged-help" and not _help_scopes(text):
            evidence_error = "packaged-help requires at least one exact help scope."
        if missing_help or missing_nodes or evidence_error or node_error:
            errors.append({
                "guide_id": source.stem,
                "missing_help_scopes": missing_help,
                "missing_nodes_by_version": missing_nodes,
                "evidence_error": evidence_error,
                "node_error": node_error,
            })
    return {"ok": not errors, "errors": errors}


def run(topic, description=""):
    """Return one packaged guide without reading arbitrary paths."""
    resolved_topic, error = _resolve_topic(topic)
    if error:
        return {"error": error, "error_code": "workflow_guide_not_found"}

    source = _GUIDE_DIR / f"{resolved_topic}.md"
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {
            "error": str(exc),
            "error_code": "workflow_guide_evidence_unavailable",
        }
    framed_description = str(description or "").strip() or f"Work on {topic}"
    try:
        guide = _render(text, {
            "description": framed_description,
            "topic": str(topic).strip(),
        })
        node_requirements = _node_requirements(guide)
    except (KeyError, ValueError) as exc:
        return {"error": str(exc), "error_code": "workflow_guide_render_failed"}

    return {
        "topic": str(topic).strip(),
        "resolved_topic": resolved_topic,
        "guide_id": resolved_topic,
        "guide_revision": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source": source.relative_to(_REPO_ROOT).as_posix(),
        "evidence_strategy": _evidence_strategy(guide),
        "source_references": _source_references(guide),
        "help_scopes": _help_scopes(guide),
        "node_references": sorted({item["reference"] for item in node_requirements}),
        "node_requirements": node_requirements,
        "tool_references": _tool_references(guide),
        "guide": guide,
    }