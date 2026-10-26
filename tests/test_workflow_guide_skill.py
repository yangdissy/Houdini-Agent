"""Tests for deterministic, on-demand workflow guide lookup."""

import re
import subprocess
from pathlib import Path

import pytest

from houdini_agent import skills


def _run_guide(topic, description=""):
    return skills.run_skill("get_workflow_guide", {
        "topic": topic,
        "description": description,
    })


def test_runtime_discovers_low_risk_workflow_guide_skill():
    skills.reload_skills()
    found = {item["name"]: item for item in skills.list_skills(category="workflow")}

    assert found["get_workflow_guide"]["risk_level"] == "low"
    assert found["get_workflow_guide"]["executable"] is True


def test_all_guides_render_task_description_without_placeholders():
    guide_dir = Path(__file__).resolve().parents[1] / "Doc" / "workflow_guides"
    topics = sorted(path.stem for path in guide_dir.glob("*.md"))

    assert len(topics) == 31
    for topic in topics:
        result = _run_guide(topic, "Build a production test")

        assert "error" not in result
        assert result["resolved_topic"] == topic
        assert "Build a production test" in result["guide"]
        assert re.search(r"\{[a-z_]+\}", result["guide"]) is None
        assert len(result["guide_revision"]) == 64
        assert result["source"] == f"Doc/workflow_guides/{topic}.md"


def test_migration_matrix_and_packaged_guides_have_identical_topics():
    doc_dir = Path(__file__).resolve().parents[1] / "Doc"
    matrix = (doc_dir / "workflow_guide_migration_matrix.md").read_text(encoding="utf-8")
    rows = re.findall(
        r"^\|\s*\d+\s*\|\s*`[^`]+\.md`\s*\|\s*`([a-z][a-z0-9_]*)`.*\|\s*(\w+)\s*\|$",
        matrix,
        re.MULTILINE,
    )
    guide_topics = {path.stem for path in (doc_dir / "workflow_guides").glob("*.md")}

    assert len(rows) == 31
    assert len({topic for topic, _status in rows}) == 31
    assert {topic for topic, _status in rows} == guide_topics
    assert {status for _topic, status in rows} == {"migrated"}


def test_every_guide_declares_tool_dependencies_explicitly():
    guide_dir = Path(__file__).resolve().parents[1] / "Doc" / "workflow_guides"
    missing = [
        path.stem
        for path in sorted(guide_dir.glob("*.md"))
        if not re.search(r"<!--\s*tools:\s*[^>]*-->", path.read_text(encoding="utf-8"))
    ]

    assert missing == []


def test_every_guide_declares_a_supported_evidence_strategy():
    guide_dir = Path(__file__).resolve().parents[1] / "Doc" / "workflow_guides"
    supported = {"local-knowledge", "packaged-help", "runtime-search"}
    strategies = {}
    for path in sorted(guide_dir.glob("*.md")):
        matches = re.findall(
            r"<!--\s*evidence:\s*([^>]*?)\s*-->",
            path.read_text(encoding="utf-8"),
        )
        assert len(matches) == 1, path.stem
        strategies[path.stem] = matches[0].strip()

    assert set(strategies.values()) <= supported
    assert set(strategies.values()) == supported


def test_local_knowledge_guides_declare_existing_sources():
    guide_dir = Path(__file__).resolve().parents[1] / "Doc" / "workflow_guides"
    for path in sorted(guide_dir.glob("*.md")):
        result = _run_guide(path.stem)
        if result["evidence_strategy"] == "local-knowledge":
            assert result["source_references"], path.stem
            assert all(reference.startswith("Doc/") for reference in result["source_references"])


def test_simulation_aliases_resolve_to_specialized_guide():
    for alias in ("smoke", "fire", "explosion"):
        result = _run_guide(alias)

        assert result["resolved_topic"] == "pyro"
        assert result["guide_id"] == "pyro"


def test_exact_subject_wins_over_alias_mapping():
    result = _run_guide("ocean")

    assert result["resolved_topic"] == "ocean"
    assert "dedicated subject guide" in result["guide"]


def test_unknown_and_unsafe_topics_fail_closed():
    unknown = _run_guide("not_a_real_topic")
    traversal = _run_guide("../pyro")

    assert unknown["error_code"] == "workflow_guide_not_found"
    assert "Available topics" in unknown["error"]
    assert traversal["error_code"] == "workflow_guide_not_found"


def test_help_scopes_are_extracted_from_rendered_guide():
    result = _run_guide("pyro")

    assert result["help_scopes"] == ["sop/pyrosolver.txt", "sop/pyrosource.txt"]
    assert result["evidence_strategy"] == "packaged-help"
    assert result["node_references"] == ["sop/pyrosolver", "sop/pyrosource"]
    assert result["node_requirements"] == [
        {"reference": "sop/pyrosolver", "version": None, "minimum_version": False},
        {"reference": "sop/pyrosource", "version": None, "minimum_version": False},
    ]
    assert result["tool_references"] == [
        "cook_sample_frames",
        "inspect_frame_range_risk",
        "search_houdini_help",
        "setup_pyro_sim",
    ]


def test_guide_audit_accepts_installed_tools_and_existing_help_pages():
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)
    available = {item["name"] for item in skills.list_skills()}
    available.update({"inspect_frame_range_risk", "cook_sample_frames"})
    referenced_scopes = {
        scope
        for guide in (module.run(topic) for topic in module._available_topics())
        for scope in guide["help_scopes"]
    }

    result = module.audit_guides(available, referenced_scopes.__contains__)

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["audited_guides"] == module._available_topics()


def test_guide_audit_fails_closed_for_missing_tool_and_help_scope():
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)

    result = module.audit_guides(set(), lambda _scope: False)

    assert result["ok"] is False
    pyro = next(error for error in result["errors"] if error["guide_id"] == "pyro")
    assert "setup_pyro_sim" in pyro["missing_tools"]
    assert "sop/pyrosource.txt" in pyro["missing_help_scopes"]


def test_guide_audit_fails_closed_for_missing_evidence_strategy(tmp_path, monkeypatch):
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)
    (tmp_path / "invalid.md").write_text(
        "# Invalid guide\n<!-- tools: -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_GUIDE_DIR", tmp_path)

    result = module.audit_guides(set(), lambda _scope: True)

    assert result["ok"] is False
    assert result["errors"] == [{
        "guide_id": "invalid",
        "missing_tools": [],
        "missing_help_scopes": [],
        "missing_sources": [],
        "evidence_error": "Guide must declare one supported evidence strategy.",
    }]


def test_packaged_guides_match_help_and_all_supported_node_catalogs():
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)

    result = module.audit_packaged_guides(("20.0.688", "20.5.684", "21.0.596"))

    assert result == {"ok": True, "errors": []}


def test_runtime_distribution_contains_all_workflow_guide_assets():
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)

    result = module.audit_runtime_assets(("20.0.688", "20.5.684", "21.0.596"))

    assert result == {"ok": True, "missing_assets": [], "guide_count": 31}


def test_workflow_guide_runtime_assets_are_tracked_for_distribution():
    root = Path(__file__).resolve().parents[1]
    expected = {
        *(f"Doc/workflow_guides/{path.name}" for path in (root / "Doc" / "workflow_guides").glob("*.md")),
        *(f"Doc/node_catalog/{path.name}" for path in (root / "Doc" / "node_catalog").glob("*.json")),
        "Doc/workflow_guide_migration_matrix.md",
        "Doc/nodes.zip",
        "Doc/vex.zip",
        "Doc/hom.zip",
    }
    try:
        listing = subprocess.run(
            ["git", "ls-files", "--", "Doc"],
            cwd=root,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        pytest.skip("git executable not available")
    if listing.returncode != 0:
        # Release tarballs / CI exports have no .git; asset presence is covered by audit_runtime_assets.
        pytest.skip(f"not a git work tree: {listing.stderr.strip()}")
    tracked = set(listing.stdout.splitlines())

    assert expected <= tracked


def test_versioned_node_requirements_apply_only_to_declared_versions():
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)
    requirements = module._node_requirements(
        "<!-- nodes: sop/newnode [20.5.684+], sop/legacy [20.0.688] -->"
    )

    new_node = next(item for item in requirements if item["reference"] == "sop/newnode")
    legacy = next(item for item in requirements if item["reference"] == "sop/legacy")
    assert module._node_applies_to(new_node, "20.0.688") is False
    assert module._node_applies_to(new_node, "20.5.684") is True
    assert module._node_applies_to(new_node, "21.0.596") is True
    assert module._node_applies_to(legacy, "20.0.688") is True
    assert module._node_applies_to(legacy, "20.5.684") is False


def test_packaged_audit_checks_versioned_nodes_only_when_applicable(tmp_path, monkeypatch):
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)
    (tmp_path / "versioned.md").write_text(
        "# Versioned\n<!-- evidence: local-knowledge -->\n"
        "<!-- nodes: sop/not_a_real_node [20.5.684+] -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_GUIDE_DIR", tmp_path)

    result = module.audit_packaged_guides(("20.0.688", "20.5.684", "21.0.596"))

    assert result["ok"] is False
    assert result["errors"][0]["missing_nodes_by_version"] == {
        "20.5.684": ["sop/not_a_real_node"],
        "21.0.596": ["sop/not_a_real_node"],
    }


def test_invalid_node_requirement_fails_closed(tmp_path, monkeypatch):
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)
    (tmp_path / "invalid.md").write_text(
        "# Invalid\n<!-- evidence: local-knowledge -->\n"
        "<!-- nodes: sop/example [20.5] -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_GUIDE_DIR", tmp_path)

    result = module.audit_packaged_guides(("20.0.688", "20.5.684", "21.0.596"))

    assert result["ok"] is False
    assert result["errors"][0]["node_error"] == (
        "Invalid node requirement: sop/example [20.5]"
    )


def test_packaged_guide_audit_fails_closed_when_catalog_is_missing():
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)

    result = module.audit_packaged_guides(("0.0.0",))

    assert result["ok"] is False
    assert result["error_code"] == "workflow_guide_evidence_unavailable"
    assert result["errors"] == []


def test_revision_changes_when_packaged_source_changes():
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)
    source = (
        Path(__file__).resolve().parents[1] / "Doc" / "workflow_guides" / "pyro.md"
    ).read_text(encoding="utf-8")

    first = module.run("pyro")["guide_revision"]
    assert first != module.hashlib.sha256((source + "changed").encode("utf-8")).hexdigest()


def test_guide_read_failure_returns_structured_error(monkeypatch):
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / "get_workflow_guide" / "SKILL.md"
    )
    module = skills._load_descriptor_entrypoint(descriptor)
    original_read_text = module.Path.read_text

    def fail_guide_read(path, *args, **kwargs):
        if path.name == "pyro.md":
            raise OSError("guide unavailable")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(module.Path, "read_text", fail_guide_read)

    result = module.run("pyro")

    assert result["error_code"] == "workflow_guide_evidence_unavailable"
    assert result["error"] == "guide unavailable"