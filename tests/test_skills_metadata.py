# -*- coding: utf-8 -*-
"""Skill metadata and import contract tests."""

import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import numpy as np

from houdini_agent.skills._contract import validate_metadata, validate_run_signature

VALID_SKILL_CATEGORIES = {
    "authoring", "docs", "geometry", "graph", "learning", "materials",
    "performance", "scene", "usd", "workflow",
}

def _builtin_skill_descriptors():
    from houdini_agent import skills

    skill_root = Path(__file__).resolve().parents[1] / "houdini_agent" / "skills"
    for skill_file in sorted(skill_root.glob("*/*/SKILL.md")):
        yield skill_file, skills._parse_skill_markdown(skill_file)


class SkillMetadataTest(unittest.TestCase):
    def test_builtin_skill_files_match_their_category_directory(self):
        misplaced = []
        for skill_file, descriptor in _builtin_skill_descriptors():
            category = skill_file.parent.parent.name
            name = skill_file.parent.name
            if descriptor.metadata["category"] != category or descriptor.metadata["name"] != name:
                misplaced.append(str(skill_file))

        self.assertEqual(misplaced, [])

    def test_network_learning_skills_are_discovered_by_runtime_loader(self):
        from houdini_agent import skills

        expected = {
            "build_hip_learning_report",
            "capture_network_memory",
            "compare_before_after_network",
            "compare_network_patterns",
            "extract_network_contract",
            "explain_network_pattern",
            "find_fragile_references",
            "find_repeated_subgraphs",
            "generalize_network_memory",
            "recall_workflow_for_task",
            "suggest_memory_cleanup",
            "validate_memory_against_scene",
        }
        skills.reload_skills()

        self.assertTrue(expected.issubset({item["name"] for item in skills.list_skills()}))

    def test_learning_skills_have_a_dedicated_category(self):
        from houdini_agent import skills

        found = {item["name"] for item in skills.list_skills(category="learning")}

        self.assertEqual(found, {
            "build_hip_learning_report",
            "capture_network_memory",
            "compare_before_after_network",
            "compare_network_patterns",
            "explain_network_pattern",
            "extract_network_contract",
            "find_fragile_references",
            "find_repeated_subgraphs",
            "generalize_network_memory",
            "recall_workflow_for_task",
            "suggest_memory_cleanup",
            "validate_memory_against_scene",
        })

    def test_loader_discovers_skills_in_category_subdirectories(self):
        from houdini_agent import skills

        skills.reload_skills()

        found = {item["name"] for item in skills.list_skills(category="learning")}
        self.assertIn("capture_network_memory", found)

    def test_runtime_discovers_instructions_only_standard_skill(self):
        from houdini_agent import skills

        skills.reload_skills()
        found = {item["name"] for item in skills.list_skills(category="docs")}
        instructions = skills.get_skill_instructions("inspect_operation_receipt")

        self.assertIn("inspect_operation_receipt", found)
        self.assertFalse(instructions["executable"])
        self.assertIn("read-only operation receipt", instructions["instructions"])

    def test_workflow_method_skills_are_instructions_only(self):
        from houdini_agent import skills

        expected = {
            "decompose_houdini_task",
            "design_houdini_parameter_ui",
            "handoff_houdini_network",
        }
        skills.reload_skills()
        found = {item["name"] for item in skills.list_skills(category="workflow")}

        self.assertTrue(expected.issubset(found))
        for name in expected:
            instructions = skills.get_skill_instructions(name)
            self.assertFalse(instructions["executable"])
            result = skills.run_skill(name, {})
            self.assertTrue(result["instructions_only"])
            self.assertEqual(result["instructions"], instructions["instructions"])

    def test_simulation_workflow_guide_is_discovered_and_validated(self):
        from houdini_agent import skills

        skills.reload_skills()
        found = {item["name"] for item in skills.list_skills(category="workflow")}
        invalid = skills.run_skill("simulation_workflow_guide", {
            "task": "Create a liquid simulation",
            "domain": "ocean",
        })
        valid = skills.run_skill("simulation_workflow_guide", {
            "task": "Create a liquid simulation",
        })

        self.assertIn("simulation_workflow_guide", found)
        self.assertEqual(invalid["error_code"], "parameter_not_in_enum")
        self.assertEqual(valid["domain"], "flip")

    def test_builtin_skills_use_known_categories(self):
        from houdini_agent import skills

        unknown = {
            item.get("category", "other")
            for item in skills.list_skills()
            if item.get("category", "other") not in VALID_SKILL_CATEGORIES
        }

        self.assertEqual(unknown, set())

    def test_all_builtin_skills_satisfy_contract(self):
        errors = []
        names = {}
        for skill_file, descriptor in _builtin_skill_descriptors():
            info = descriptor.metadata
            metadata_error = validate_metadata(info, expected_name=skill_file.parent.name)
            module = None
            signature_error = None
            if descriptor.entrypoint:
                module = __import__("houdini_agent.skills", fromlist=["skills"])._load_descriptor_entrypoint(descriptor)
                signature_error = validate_run_signature(info, module.run)
            if metadata_error:
                errors.append(f"{skill_file}: {metadata_error}")
            if signature_error:
                errors.append(f"{skill_file}: {signature_error}")
            previous = names.get(info.get("name"))
            if previous:
                errors.append(
                    f"duplicate name {info.get('name')}: {previous} and {skill_file}"
                )
            names[info.get("name")] = str(skill_file)

        self.assertEqual(errors, [])

    def test_builtin_categories_have_no_legacy_skill_modules(self):
        skill_root = Path(__file__).resolve().parents[1] / "houdini_agent" / "skills"
        leftovers = [
            path.relative_to(skill_root).as_posix()
            for category in VALID_SKILL_CATEGORIES
            for path in (skill_root / category).glob("*.py")
            if not path.name.startswith("_")
        ]

        self.assertEqual(leftovers, [])

    def test_list_skills_semantically_ranks_cross_language_query(self):
        from houdini_agent import skills

        fake_embedder = mock.Mock(is_semantic=True)
        fake_embedder.encode.return_value = np.array([1.0, 0.0], dtype=np.float32)
        fake_embedder.encode_batch.side_effect = lambda texts: np.array([
            [1.0, 0.0] if "analyze_cook_performance" in text else [0.0, 1.0]
            for text in texts
        ], dtype=np.float32)
        fake_embedder.batch_cosine_similarity.side_effect = lambda query, matrix: matrix @ query

        with mock.patch("houdini_agent.utils.embedding.get_embedder", return_value=fake_embedder):
            found = skills.list_skills(query="检查哪些节点拖慢了运算", limit=1)

        self.assertEqual(found[0]["name"], "analyze_cook_performance")

    def test_list_skills_uses_bilingual_fallback_without_semantic_model(self):
        from houdini_agent import skills

        fake_embedder = mock.Mock(is_semantic=False)
        fake_embedder.encode.return_value = np.array([1.0, 0.0], dtype=np.float32)
        fake_embedder.encode_batch.side_effect = lambda texts: np.array([
            [1.0, 0.0] if "analyze_cook_performance" in text else [0.0, 1.0]
            for text in texts
        ], dtype=np.float32)
        fake_embedder.batch_cosine_similarity.side_effect = lambda query, matrix: matrix @ query

        with mock.patch("houdini_agent.utils.embedding.get_embedder", return_value=fake_embedder):
            found = skills.list_skills(query="检查哪些节点拖慢了运算", limit=1)

        self.assertEqual(found[0]["name"], "analyze_cook_performance")

    def test_list_skills_bilingual_fallback_ranks_performance_query(self):
        from houdini_agent import skills

        found = skills.list_skills(query="检查哪些节点拖慢了运算", limit=1)

        self.assertEqual(found[0]["name"], "analyze_cook_performance")

    def test_disabled_skill_is_hidden_and_cannot_run(self):
        from houdini_agent import skills

        registry = mock.Mock()
        registry.get_disabled_tools.return_value = ["skill_analyze_cook_performance"]
        with mock.patch(
            "houdini_agent.utils.tool_registry.get_tool_registry",
            return_value=registry,
        ):
            found = skills.list_skills()
            result = skills.run_skill("analyze_cook_performance", {})

        self.assertNotIn("analyze_cook_performance", {item["name"] for item in found})
        self.assertEqual(result["error"], "Skill 已禁用: analyze_cook_performance")

    def test_run_skill_enforces_declared_parameter_contract(self):
        from houdini_agent import skills

        module = mock.Mock()
        module.SKILL_INFO = {
            "name": "contract_test",
            "parameters": {
                "node_path": {"type": "string", "required": True},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
                "mode": {"type": "string", "default": "fast", "enum": ["fast", "full"]},
            },
        }
        module.run = mock.Mock(return_value={"ok": True})
        with mock.patch.dict(skills._registry, {"contract_test": module}, clear=False), mock.patch.object(
            skills, "_loaded", True
        ):
            missing = skills.run_skill("contract_test", {})
            wrong_type = skills.run_skill("contract_test", {"node_path": 42})
            unknown = skills.run_skill("contract_test", {"node_path": "/obj", "extra": True})
            below_minimum = skills.run_skill("contract_test", {"node_path": "/obj", "limit": 0})
            invalid_enum = skills.run_skill("contract_test", {"node_path": "/obj", "mode": "other"})
            valid = skills.run_skill("contract_test", {"node_path": "/obj"})

        self.assertIn("node_path", missing["error"])
        self.assertEqual(missing["error_code"], "missing_required_parameter")
        self.assertIn("必须是 string", wrong_type["error"])
        self.assertIn("extra", unknown["error"])
        self.assertEqual(below_minimum["error_code"], "parameter_below_minimum")
        self.assertEqual(invalid_enum["error_code"], "parameter_not_in_enum")
        self.assertEqual(valid, {"ok": True})
        module.run.assert_called_once_with(node_path="/obj", limit=5, mode="fast")

    def test_reload_skills_discovers_user_directory(self):
        from houdini_agent import skills

        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "custom_test.py").write_text(
                "SKILL_INFO = {'name': 'custom_test', 'description': 'test'}\n"
                "def run(**kwargs):\n"
                "    return {'value': kwargs.get('value')}\n",
                encoding="utf-8",
            )
            with mock.patch.object(skills, "_get_user_skill_dir", return_value=Path(temp_dir)):
                skills.reload_skills()
                result = skills.run_skill("custom_test", {"value": 42})

        self.assertEqual(result, {"value": 42})
        with mock.patch.object(skills, "_get_user_skill_dir", return_value=None):
            skills.reload_skills()

    def test_descriptor_discovery_does_not_import_entrypoint_until_run(self):
        from houdini_agent import skills

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "descriptor_test")
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            marker = root / "imported.txt"
            (root / "SKILL.md").write_text(
                '---\n{"name":"descriptor_test","description":"test",'
                '"category":"geometry","risk_level":"low","parameters":{},'
                '"entrypoint":"scripts/main.py:run"}\n---\nRun only when requested.\n',
                encoding="utf-8",
            )
            (scripts / "main.py").write_text(
                f'from pathlib import Path\nPath({str(marker)!r}).write_text("loaded")\n'
                'def run():\n    return {"ok": True}\n',
                encoding="utf-8",
            )

            registry_before = dict(skills._registry)
            try:
                skills._registry.clear()
                skills._load_skill_descriptors(Path(temp_dir))
                self.assertFalse(marker.exists())
                self.assertEqual(
                    skills.get_skill_instructions("descriptor_test")["instructions"],
                    "Run only when requested.",
                )
                with mock.patch.object(skills, "_loaded", True):
                    self.assertEqual(skills.run_skill("descriptor_test", {}), {"ok": True})
                self.assertTrue(marker.exists())
            finally:
                skills._registry.clear()
                skills._registry.update(registry_before)

    def test_descriptor_rejects_nonstandard_entrypoint(self):
        from houdini_agent import skills

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "contract_test")
            root.mkdir()
            (root / "SKILL.md").write_text(
                '---\n{"name":"contract_test","description":"test",'
                '"category":"geometry","risk_level":"low","parameters":{},'
                '"entrypoint":"scripts/other.py:execute"}\n---\nTest.\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "scripts/main.py:run"):
                skills._parse_skill_markdown(root / "SKILL.md")

    def test_registry_clear_removes_loaded_descriptor_module_cache(self):
        from houdini_agent import skills

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "cache_test")
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            (root / "SKILL.md").write_text(
                '---\n{"name":"cache_test","description":"test",'
                '"category":"geometry","risk_level":"low","parameters":{},'
                '"entrypoint":"scripts/main.py:run"}\n---\nCache test.\n',
                encoding="utf-8",
            )
            (scripts / "main.py").write_text(
                'def run():\n    return {"ok": True}\n', encoding="utf-8"
            )

            skills._clear_registry()
            skills._load_skill_descriptors(Path(temp_dir))
            descriptor = skills._registry["cache_test"]
            skills._load_descriptor_entrypoint(descriptor)
            module_name = descriptor.module_name
            self.assertIn(module_name, sys.modules)

            skills._clear_registry()

            self.assertNotIn(module_name, sys.modules)
            with mock.patch.object(skills, "_get_user_skill_dir", return_value=None):
                skills.reload_skills()

    def test_legacy_loader_skips_python_inside_descriptor_bundle(self):
        from houdini_agent import skills

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "bundle_test")
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            (root / "SKILL.md").write_text("descriptor", encoding="utf-8")
            (scripts / "main.py").write_text(
                "raise RuntimeError('must not import')\n", encoding="utf-8"
            )
            diagnostics_before = list(skills._load_diagnostics)
            try:
                skills._load_diagnostics.clear()
                skills._load_skills_from_dir(Path(temp_dir))
                self.assertEqual(skills._load_diagnostics, [])
            finally:
                skills._load_diagnostics.clear()
                skills._load_diagnostics.extend(diagnostics_before)


if __name__ == "__main__":
    unittest.main()