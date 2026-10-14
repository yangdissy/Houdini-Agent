"""Tests for workflow blueprint skills."""

from pathlib import Path

from houdini_agent import skills


def _run(name):
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "workflow" / name / "SKILL.md"
    )
    return skills._load_descriptor_entrypoint(descriptor).run


cache_pipeline = _run("setup_cache_pipeline")
copernicus_pipeline = _run("setup_copernicus_pipeline")
export_pipeline = _run("setup_export_pipeline")
heightfield_terrain = _run("setup_heightfield_terrain")
instance_scatter = _run("setup_instance_scatter")
kinefx_pipeline = _run("setup_kinefx_pipeline")
material_lookdev = _run("setup_material_lookdev")
pdg_pipeline = _run("setup_pdg_batch_pipeline")
procedural_modeling = _run("procedural_modeling_guide")
usd_scene_assembly = _run("usd_scene_assembly_guide")


def _assert_blueprint(result):
    assert "error" not in result
    assert result["nodes"]
    assert result["execution"]["tool"] == "create_nodes_batch"
    assert "dry_run=True" in result["execution"]["notes"]


def test_cache_pipeline_builds_versioned_path():
    result = cache_pipeline("/obj/geo1/OUT", "sim", version=2, frame_start=10, frame_end=20)
    _assert_blueprint(result)
    assert result["cache_path"] == "$HIP/cache/sim/v002/sim.$F4.bgeo.sc"


def test_material_lookdev_supports_karma():
    result = material_lookdev("hero", mode="karma")
    _assert_blueprint(result)
    assert result["parent_path"] == "/stage"
    assert result["module_boundaries"] == [
        "material definition", "material binding", "lookdev lighting", "review output",
    ]
    assert "decompose_houdini_task" in result["recommended_existing_skills"]


def test_instance_scatter_has_two_source_contracts():
    result = instance_scatter("/obj/geo1/GROUND", "/obj/tree/OUT", count=500)
    _assert_blueprint(result)
    assert result["surface_node_path"].endswith("GROUND")
    assert result["instance_node_path"].endswith("OUT")


def test_heightfield_pipeline_can_include_erosion():
    result = heightfield_terrain("island", resolution=512, erosion=True)
    _assert_blueprint(result)
    assert "erosion" in {item["id"] for item in result["nodes"]}


def test_export_pipeline_selects_format_and_path():
    result = export_pipeline("/obj/geo1/OUT", "abc", "hero", 1, 48)
    _assert_blueprint(result)
    assert result["export_path"] == "$HIP/export/hero/hero.abc"


def test_copernicus_pipeline_has_guarded_output():
    result = copernicus_pipeline("surface", 1024, "exr")
    _assert_blueprint(result)
    assert result["output_path"].endswith("surface_packed.exr")
    assert [item["role"] for item in result["module_boundaries"]] == [
        "input_or_generation", "processing", "channel_pack", "file_output",
    ]


def test_kinefx_pipeline_selects_mode():
    result = kinefx_pipeline("/obj/character/SKELETON", "capture")
    _assert_blueprint(result)
    assert result["mode"] == "capture"
    assert "weights" in result["module_boundaries"]


def test_procedural_modeling_only_routes_complex_work_to_decomposition():
    simple = procedural_modeling("Make a box", complexity="simple")
    complex_result = procedural_modeling("Build a modular city", complexity="complex")

    assert "decompose_houdini_task" not in simple["recommended_existing_skills"]
    assert "design_houdini_parameter_ui" not in simple["recommended_existing_skills"]
    assert "decompose_houdini_task" in complex_result["recommended_existing_skills"]
    assert "handoff_houdini_network" in complex_result["recommended_existing_skills"]


def test_usd_guide_exposes_observable_module_boundaries():
    result = usd_scene_assembly("Assemble a hero asset for Karma")

    assert "materials and bindings" in result["module_boundaries"]
    assert "render settings and output" in result["module_boundaries"]
    assert "design_houdini_parameter_ui" in result["recommended_existing_skills"]


def test_structured_skill_recommendations_resolve_to_registry():
    results = [
        copernicus_pipeline("surface"),
        kinefx_pipeline("/obj/character/SKELETON", "rig"),
        material_lookdev("hero", mode="karma"),
        procedural_modeling("Build a modular city", complexity="complex"),
        usd_scene_assembly("Assemble a hero asset for Karma"),
    ]
    registered = {item["name"] for item in skills.list_skills()}

    for result in results:
        assert set(result.get("recommended_existing_skills", [])) <= registered


def test_pdg_pipeline_does_not_request_cook():
    result = pdg_pipeline("/out/cache", wedge_count=8)
    _assert_blueprint(result)
    assert result["execution"]["tool"] == "create_nodes_batch"
    assert "Do not cook" in result["execution"]["notes"]