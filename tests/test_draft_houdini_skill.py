# -*- coding: utf-8 -*-
"""Tests for the read-only Houdini Skill drafter."""

from pathlib import Path
from unittest import mock

from houdini_agent import skills


_DESCRIPTOR = skills._parse_skill_markdown(
    Path(__file__).resolve().parents[1]
    / "houdini_agent" / "skills" / "authoring" / "draft_houdini_skill" / "SKILL.md"
)
draft_houdini_skill = skills._load_descriptor_entrypoint(_DESCRIPTOR)


def test_interview_asks_one_decision_at_a_time_with_recommendation():
    first = draft_houdini_skill.run()

    assert first["status"] == "question"
    assert first["question_id"] == "purpose"
    assert "干什么" in first["question"]
    assert first["recommendation"]
    assert "question" in first
    assert "questions" not in first

    second = draft_houdini_skill.run(answers={"purpose": "检查 SOP 几何中的退化面并返回统计。"})

    assert second["question_id"] == "audience_and_context"
    assert second["next_params"]["answers"]["purpose"].startswith("检查 SOP")


def test_interview_requires_final_confirmation_before_drafting():
    answers = {
        "purpose": "检查 SOP 几何中的退化面并返回统计。",
        "audience_and_context": "建模组在资产交付前检查输出节点。",
        "expected_result": "返回退化面数量、位置和修复建议。",
        "boundaries": "只读，不自动修改几何；节点不存在时停止。",
        "name": "analyze_degenerate_faces",
        "category": "geometry",
        "parameters": [{
            "name": "node_path", "type": "string",
            "description": "SOP node path.", "required": True,
        }],
        "requires_hou": True,
        "modifies_scene": False,
        "risk_level": "low",
        "examples": ["检查 /obj/geo1/OUT", "节点路径不存在时返回明确错误"],
    }

    review = draft_houdini_skill.run(answers=answers)

    assert review["status"] == "question"
    assert review["question_id"] == "confirmed"
    assert review["design_summary"]["name"] == "analyze_degenerate_faces"
    assert "skill_source" not in review

    with mock.patch.object(draft_houdini_skill, "_similar_skills", return_value=[]):
        ready = draft_houdini_skill.run(answers=answers, confirmed=True)

    assert ready["status"] == "ready"
    assert ready["name"] == "analyze_degenerate_faces"
    assert "def run(node_path):" in ready["skill_source"]


def test_draft_is_reviewable_and_never_writes_or_executes():
    with mock.patch.object(draft_houdini_skill, "_similar_skills", return_value=[]):
        result = draft_houdini_skill.run(
            name="analyze_uv_quality",
            intent="Analyze UV overlap and degenerate islands. Read-only.",
            category="geometry",
            parameters=[{
                "name": "node_path",
                "type": "string",
                "description": "SOP node path.",
                "required": True,
            }],
            examples=["检查 /obj/geo1/OUT 的 UV 质量"],
            requires_hou=True,
        )

    assert result["module_path"] == "houdini_agent/skills/geometry/analyze_uv_quality/scripts/main.py"
    assert result["skill_root"] == "houdini_agent/skills/geometry/analyze_uv_quality"
    assert result["written"] is False
    assert result["executed"] is False
    assert '"name":"analyze_uv_quality"' in result["skill_files"]["SKILL.md"]
    assert '"entrypoint":"scripts/main.py:run"' in result["skill_files"]["SKILL.md"]
    assert "SKILL_INFO" not in result["skill_source"]
    assert "def run(node_path):" in result["skill_source"]
    assert "import hou" in result["skill_source"]
    assert "skills._load_descriptor_entrypoint" in result["test_source"]
    assert "def test_analyze_uv_quality_returns_structured_result():" in result["test_source"]
    assert result["evaluation_cases"][0]["prompt"].startswith("检查")


def test_draft_rejects_unknown_category():
    result = draft_houdini_skill.run("valid_name", "Do something.", "future")

    assert "Unknown category" in result["error"]
    assert result["written"] is False


def test_draft_preserves_parameter_limits():
    with mock.patch.object(draft_houdini_skill, "_similar_skills", return_value=[]):
        result = draft_houdini_skill.run(
            name="analyze_limited_sample",
            intent="Analyze a bounded sample.",
            category="geometry",
            parameters=[{
                "name": "limit", "type": "integer", "description": "Sample limit.",
                "default": 10, "minimum": 1, "maximum": 100,
            }, {
                "name": "mode", "type": "string", "description": "Analysis mode.",
                "default": "fast", "enum": ["fast", "full"],
            }],
        )

    descriptor = result["skill_files"]["SKILL.md"]
    assert '"minimum":1' in descriptor
    assert '"maximum":100' in descriptor
    assert '"enum":["fast","full"]' in descriptor


def test_draft_rejects_low_risk_scene_mutation():
    result = draft_houdini_skill.run(
        "build_nodes", "Build nodes.", "workflow", modifies_scene=True, risk_level="low"
    )

    assert "scene-mutating" in result["error"]


def test_workflow_draft_requires_blueprint_review():
    with mock.patch.object(draft_houdini_skill, "_similar_skills", return_value=[]):
        result = draft_houdini_skill.run(
            "setup_custom_pipeline", "Draft a custom pipeline.", "workflow", risk_level="normal"
        )

    assert any("blueprint only" in check for check in result["review_checks"])