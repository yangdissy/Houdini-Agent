# -*- coding: utf-8 -*-
"""Versioned Houdini node catalog generation and loading contracts."""

import json
from unittest import mock

import pytest

from houdini_agent.utils.node_catalog import (
    build_node_catalog,
    catalog_to_node_index,
    load_node_catalog,
    render_node_catalog_json,
)


class _NodeType:
    def __init__(self, description=None, raises=False):
        self._description = description
        self._raises = raises

    def description(self):
        if self._raises:
            raise RuntimeError("description unavailable")
        return self._description


class _Category:
    def __init__(self, node_types):
        self._node_types = node_types

    def nodeTypes(self):
        return self._node_types


class _Hou:
    @staticmethod
    def applicationVersion():
        return (21, 0, 596)

    @staticmethod
    def applicationVersionString():
        return "21.0.596"

    @staticmethod
    def nodeTypeCategories():
        return {
            "Sop": _Category({
                "scatter::2.0": _NodeType("Scatter points"),
                "attribwrangle": _NodeType("Run VEX"),
                "broken": _NodeType(raises=True),
            }),
            "Object": _Category({"geo": _NodeType("Geometry container")}),
        }


def test_catalog_is_versioned_sorted_and_keeps_description_failures():
    catalog = build_node_catalog(_Hou)

    assert catalog["schema_version"] == 1
    assert catalog["source"] == "hou.nodeTypeCategories"
    assert catalog["houdini_version"] == [21, 0, 596]
    assert catalog["houdini_version_string"] == "21.0.596"
    assert [(node["category"], node["type_name"]) for node in catalog["nodes"]] == [
        ("object", "geo"),
        ("sop", "attribwrangle"),
        ("sop", "broken"),
        ("sop", "scatter::2.0"),
    ]
    assert catalog["nodes"][2]["description"] == ""


def test_catalog_json_is_byte_stable():
    first = render_node_catalog_json(build_node_catalog(_Hou))
    second = render_node_catalog_json(build_node_catalog(_Hou))

    assert first == second
    assert first.endswith("\n")


def test_catalog_converts_to_existing_mcp_node_index_shape():
    index = catalog_to_node_index(build_node_catalog(_Hou))

    assert index["object"] == [("geo", "Geometry container", "object/geo")]
    assert index["sop"][0] == ("attribwrangle", "Run VEX", "sop/attribwrangle")
    assert index["sop"][-1] == (
        "scatter::2.0", "Scatter points", "sop/scatter::2.0",
    )


def test_catalog_loader_rejects_schema_or_houdini_version_mismatch(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(render_node_catalog_json(build_node_catalog(_Hou)), encoding="utf-8")

    assert load_node_catalog(path, expected_houdini_version=(21, 0, 596))["nodes"]
    with pytest.raises(ValueError, match="Houdini version"):
        load_node_catalog(path, expected_houdini_version=(20, 5, 1))

    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 999
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        load_node_catalog(path)


def test_generator_writes_checks_and_detects_drift(tmp_path):
    from scripts import generate_houdini_node_catalog as generator

    output = tmp_path / "catalog.json"
    with mock.patch.object(generator, "generate", return_value="catalog\n"):
        assert generator.main(["--output", str(output)]) == 0
        assert generator.main(["--output", str(output), "--check"]) == 0
        output.write_text("stale\n", encoding="utf-8")
        assert generator.main(["--output", str(output), "--check"]) == 1


def test_generator_defaults_to_versioned_output(tmp_path):
    from scripts import generate_houdini_node_catalog as generator

    rendered = render_node_catalog_json(build_node_catalog(_Hou))
    with mock.patch.object(generator, "generate", return_value=rendered):
        assert generator.main(["--output-dir", str(tmp_path)]) == 0

    output = tmp_path / "houdini_node_catalog-21.0.596.json"
    assert output.read_text(encoding="utf-8") == rendered
    with mock.patch.object(generator, "generate", return_value=rendered):
        assert generator.main([
            "--output-dir", str(tmp_path), "--check",
        ]) == 0


def test_generator_default_output_is_in_doc_knowledge_base():
    from scripts import generate_houdini_node_catalog as generator

    assert generator.DEFAULT_OUTPUT_DIR == generator.REPO_ROOT / "Doc" / "node_catalog"


def test_generator_fails_closed_without_houdini(tmp_path):
    from scripts import generate_houdini_node_catalog as generator

    with mock.patch.object(generator, "generate", side_effect=RuntimeError("use hython")):
        assert generator.main(["--output", str(tmp_path / "catalog.json")]) == 2
