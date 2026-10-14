from pathlib import Path

from houdini_agent import skills


_DESCRIPTOR = skills._parse_skill_markdown(
    Path(__file__).resolve().parents[1]
    / "houdini_agent" / "skills" / "scene" / "debug_scene_workflow" / "SKILL.md"
)
debug_scene_workflow = skills._load_descriptor_entrypoint(_DESCRIPTOR)


def test_recommended_skills_use_registered_migration_names():
    result = debug_scene_workflow.run("Stage material is missing", scope="usd")
    registered = {item["name"] for item in skills.list_skills()}

    assert "trace_node_dependencies" in result["recommended_skills"]
    assert "trace_dependencies" not in result["recommended_skills"]
    assert "inspect_lop_stage" in result["recommended_skills"]
    assert set(result["recommended_skills"]) <= registered