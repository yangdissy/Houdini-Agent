# -*- coding: utf-8 -*-
"""Tests for governed user Skill installation."""

from pathlib import Path
from unittest import mock

from houdini_agent import skills


_DESCRIPTOR = skills._parse_skill_markdown(
    Path(__file__).resolve().parents[1]
    / "houdini_agent" / "skills" / "authoring" / "install_houdini_skill" / "SKILL.md"
)
install_houdini_skill = skills._load_descriptor_entrypoint(_DESCRIPTOR)


SOURCE = '''def run(node_path):
    return {"node_path": node_path, "ok": True}
'''
FILES = {
    "SKILL.md": '''---
{"name":"user_quality_check","category":"geometry","description":"Return a reviewed quality summary.","risk_level":"low","parameters":{"node_path":{"type":"string","description":"SOP node path.","required":true}},"entrypoint":"scripts/main.py:run"}
---
# User Quality Check
''',
    "scripts/main.py": SOURCE,
}


def test_preview_validates_without_writing(tmp_path):
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=tmp_path), mock.patch.object(
        install_houdini_skill, "_builtin_skill_exists", return_value=False
    ):
        result = install_houdini_skill.run(skill_files=FILES, mode="preview")

    assert result["installed"] is False
    assert result["executed"] is False
    assert result["checks"]["syntax_valid"] is True
    assert not Path(result["target_path"]).exists()


def test_preview_rejects_unknown_descriptor_fields(tmp_path):
    files = dict(FILES)
    files["SKILL.md"] = files["SKILL.md"].replace(
        '"entrypoint":"scripts/main.py:run"',
        '"entrypoint":"scripts/main.py:run","extra":true',
    )
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=tmp_path):
        result = install_houdini_skill.run(skill_files=files, mode="preview")

    assert "Unknown SKILL.md frontmatter fields: extra" in result["error"]


def test_install_writes_atomically_without_importing_source(tmp_path):
    marker = tmp_path / "imported.txt"
    files = dict(FILES)
    files["scripts/main.py"] = SOURCE + f'\nPath = __import__("pathlib").Path\nPath({str(marker)!r}).write_text("imported")\n'
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=tmp_path), mock.patch.object(
        install_houdini_skill, "_builtin_skill_exists", return_value=False
    ):
        result = install_houdini_skill.run(skill_files=files, mode="install")

    target = tmp_path / "user_quality_check"
    assert result["installed"] is True
    assert result["active"] is False
    assert result["executed"] is False
    assert (target / "SKILL.md").read_text(encoding="utf-8") == files["SKILL.md"]
    assert (target / "scripts" / "main.py").read_text(encoding="utf-8") == files["scripts/main.py"]
    assert not marker.exists()
    assert not (tmp_path / "user_quality_check.partial").exists()


def test_install_fails_closed_without_configured_user_directory():
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=None):
        result = install_houdini_skill.run(skill_files=FILES, mode="install")

    assert "user_skill_dir" in result["error"]
    assert result["installed"] is False


def test_configured_user_directory_is_initialized_for_bound_user(tmp_path):
    from houdini_agent import skills

    with mock.patch("shared.user_paths.get_repo_root", return_value=str(tmp_path)):
        skills.set_current_user("skill_tester")

        user_dir = install_houdini_skill._configured_user_dir()

    assert user_dir == tmp_path / "cache" / "users" / "skill_tester" / "skills"
    assert user_dir.is_dir()
    config = tmp_path / "cache" / "users" / "skill_tester" / "config.ini"
    assert "[skills]" in config.read_text(encoding="utf-8")


def test_install_rejects_draft_placeholder(tmp_path):
    draft = dict(FILES)
    draft["scripts/main.py"] = SOURCE.replace('return {"node_path": node_path, "ok": True}', 'return {"status": "draft"}')
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=tmp_path):
        result = install_houdini_skill.run(skill_files=draft, mode="install")

    assert "Draft placeholder" in result["error"]


def test_preview_rejects_invalid_parameter_limits(tmp_path):
    invalid = dict(FILES)
    invalid["SKILL.md"] = FILES["SKILL.md"].replace(
        '"required":true}', '"required":true,"minimum":10,"maximum":1}'
    )
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=tmp_path):
        result = install_houdini_skill.run(skill_files=invalid, mode="preview")

    assert "minimum cannot exceed maximum" in result["error"]


def test_install_rejects_existing_skill(tmp_path):
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=tmp_path), mock.patch.object(
        install_houdini_skill, "_builtin_skill_exists", return_value=True
    ):
        result = install_houdini_skill.run(skill_files=FILES, mode="preview")

    assert "will not be overwritten" in result["error"]
    assert not (tmp_path / "user_quality_check").exists()


def test_failed_activation_keeps_source_and_rolls_back_authorization(tmp_path):
    target = tmp_path / "user_quality_check"
    (target / "scripts").mkdir(parents=True)
    (target / "SKILL.md").write_text(FILES["SKILL.md"], encoding="utf-8")
    (target / "scripts" / "main.py").write_text(SOURCE, encoding="utf-8")
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=tmp_path), mock.patch.object(
        install_houdini_skill, "_activate", side_effect=RuntimeError("import failed")
    ):
        result = install_houdini_skill.run(action="activate", skill_name="user_quality_check")

    assert "remains inactive" in result["error"]
    assert result["active"] is False
    assert (target / "scripts" / "main.py").read_text(encoding="utf-8") == SOURCE


def test_activate_requires_installed_source(tmp_path):
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=tmp_path):
        result = install_houdini_skill.run(action="activate", skill_name="missing_skill")

    assert "does not exist" in result["error"]


def test_activate_imports_only_after_explicit_action(tmp_path):
    target = tmp_path / "user_quality_check"
    (target / "scripts").mkdir(parents=True)
    (target / "SKILL.md").write_text(FILES["SKILL.md"], encoding="utf-8")
    (target / "scripts" / "main.py").write_text(SOURCE, encoding="utf-8")
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=tmp_path), mock.patch.object(
        install_houdini_skill, "_activate"
    ) as activate:
        result = install_houdini_skill.run(action="activate", skill_name="user_quality_check")

    activate.assert_called_once_with("user_quality_check")
    assert result["active"] is True


def test_install_does_not_require_preview(tmp_path):
    with mock.patch.object(install_houdini_skill, "_configured_user_dir", return_value=tmp_path), mock.patch.object(
        install_houdini_skill, "_builtin_skill_exists", return_value=False
    ):
        result = install_houdini_skill.run(skill_files=FILES, mode="install")

    assert result["installed"] is True
    assert (tmp_path / "user_quality_check" / "scripts" / "main.py").read_text(encoding="utf-8") == SOURCE