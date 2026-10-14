# -*- coding: utf-8 -*-
"""Tests for persistent user Skill activation filtering."""

import json

from houdini_agent import skills


SOURCE = '''SKILL_INFO = {
    "name": "existing_user_skill",
    "category": "geometry",
    "description": "Existing user Skill.",
    "risk_level": "low",
    "parameters": {},
}

def run():
    return {"ok": True}
'''


def test_missing_manifest_migrates_existing_skills_as_active(tmp_path):
    (tmp_path / "existing_user_skill.py").write_text(SOURCE, encoding="utf-8")

    active = skills._read_active_user_skills(tmp_path)

    assert active == {"existing_user_skill"}
    payload = json.loads((tmp_path / ".active_skills.json").read_text(encoding="utf-8"))
    assert payload == {"active_skills": ["existing_user_skill"]}


def test_existing_manifest_does_not_auto_activate_new_file(tmp_path):
    skills._write_active_user_skills(tmp_path, set())
    (tmp_path / "existing_user_skill.py").write_text(SOURCE, encoding="utf-8")

    assert skills._read_active_user_skills(tmp_path) == set()


def test_invalid_manifest_fails_closed(tmp_path):
    (tmp_path / ".active_skills.json").write_text("not json", encoding="utf-8")

    assert skills._read_active_user_skills(tmp_path) is None


def test_loader_rejects_metadata_name_that_does_not_match_authorized_filename(tmp_path):
    source = SOURCE.replace('"existing_user_skill"', '"different_name"', 1)
    (tmp_path / "existing_user_skill.py").write_text(source, encoding="utf-8")
    registry_before = dict(skills._registry)
    try:
        skills._registry.clear()
        skills._load_skills_from_dir(
            tmp_path, prefix="user_", allowed_names={"existing_user_skill"}
        )
        assert "different_name" not in skills._registry
    finally:
        skills._registry.clear()
        skills._registry.update(registry_before)


def test_loader_records_structured_diagnostic_for_invalid_skill(tmp_path):
    (tmp_path / "broken_skill.py").write_text("raise RuntimeError('broken import')\n", encoding="utf-8")
    diagnostics_before = list(skills._load_diagnostics)
    try:
        skills._load_diagnostics.clear()
        skills._load_skills_from_dir(tmp_path, prefix="user_", allowed_names={"broken_skill"})
        diagnostics = list(skills._load_diagnostics)
        assert diagnostics == [{
            "skill_file": str(tmp_path / "broken_skill.py"),
            "phase": "import_or_contract",
            "error_code": "skill_load_failed",
            "message": "broken import",
        }]
    finally:
        skills._load_diagnostics.clear()
        skills._load_diagnostics.extend(diagnostics_before)


def test_duplicate_legacy_and_descriptor_candidates_are_both_rejected(tmp_path):
    (tmp_path / "existing_user_skill.py").write_text(SOURCE, encoding="utf-8")
    descriptor_root = tmp_path / "existing_user_skill"
    descriptor_root.mkdir()
    (descriptor_root / "SKILL.md").write_text(
        '---\n{"name":"existing_user_skill","description":"duplicate",'
        '"category":"geometry","risk_level":"low","parameters":{}}\n'
        '---\nDuplicate descriptor.\n',
        encoding="utf-8",
    )
    registry_before = dict(skills._registry)
    sources_before = dict(skills._registry_sources)
    conflicts_before = set(skills._conflicted_names)
    diagnostics_before = list(skills._load_diagnostics)
    try:
        skills._registry.clear()
        skills._registry_sources.clear()
        skills._conflicted_names.clear()
        skills._load_diagnostics.clear()
        allowed = {"existing_user_skill"}
        skills._load_skills_from_dir(tmp_path, prefix="user_", allowed_names=allowed)
        skills._load_skill_descriptors(
            tmp_path, allowed_names=allowed, source="user_descriptor"
        )

        assert "existing_user_skill" not in skills._registry
        assert "existing_user_skill" in skills._conflicted_names
        assert any(
            diagnostic["phase"] == "duplicate_name"
            for diagnostic in skills._load_diagnostics
        )
    finally:
        skills._registry.clear()
        skills._registry.update(registry_before)
        skills._registry_sources.clear()
        skills._registry_sources.update(sources_before)
        skills._conflicted_names.clear()
        skills._conflicted_names.update(conflicts_before)
        skills._load_diagnostics.clear()
        skills._load_diagnostics.extend(diagnostics_before)