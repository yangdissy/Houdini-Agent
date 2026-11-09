import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from houdini_agent.utils.memory_store import MemoryStore, ProceduralRecord
from houdini_agent.utils.reflection import ReflectionModule
from tests.test_team_memory import FakeEmbedder


class FakeAIClient:
    def __init__(self, payload):
        self.payload = payload

    def chat_stream(self, **_kwargs):
        yield {"type": "content", "content": json.dumps(self.payload)}


class ProceduralMemoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.store = MemoryStore(
            db_path=Path(self.temp_dir.name) / "agent_memory.db",
            embedder=FakeEmbedder(),
        )

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_usage_statistics_record_success_and_failure(self):
        record = ProceduralRecord(
            strategy_name="validate_before_cook",
            description="Validate the node path before cooking",
            origin="manual",
            source_episodes=["episode-1"],
            scope={"houdini_version": "21.0"},
            validated_at=123.0,
            supersedes_id="older-strategy",
        )
        self.store.add_procedural(record)

        self.store.update_procedural_usage(record.id, success=True)
        self.store.update_procedural_usage(record.id, success=False)

        saved = self.store.get_procedural(record.id)
        self.assertEqual(saved.usage_count, 2)
        self.assertAlmostEqual(saved.success_rate, 0.5)
        self.assertGreaterEqual(saved.last_used, record.last_used)
        self.assertEqual(saved.origin, "manual")
        self.assertEqual(saved.source_episodes, ["episode-1"])
        self.assertEqual(saved.scope, {"houdini_version": "21.0"})
        self.assertEqual(saved.validated_at, 123.0)
        self.assertEqual(saved.supersedes_id, "older-strategy")

    def test_edit_style_replace_preserves_lifecycle_and_provenance(self):
        original = ProceduralRecord(
            strategy_name="validate_before_cook",
            description="Validate first",
            status="trial",
            origin="deep_sleep",
            source_episodes=["episode-1"],
            cited_count=2,
            scope={"houdini_version": "21.0"},
        )
        self.store.add_procedural(original)

        edited = ProceduralRecord(
            id=original.id,
            strategy_name=original.strategy_name,
            description="Validate the path first",
            status=original.status,
            origin=original.origin,
            source_episodes=original.source_episodes,
            cited_count=original.cited_count,
            scope=original.scope,
        )
        self.store.add_procedural(edited)

        saved = self.store.get_procedural(original.id)
        self.assertEqual(saved.status, "trial")
        self.assertEqual(saved.origin, "deep_sleep")
        self.assertEqual(saved.source_episodes, ["episode-1"])
        self.assertEqual(saved.cited_count, 2)
        self.assertEqual(saved.scope, {"houdini_version": "21.0"})

    def test_manual_lifecycle_transitions_are_strict_and_atomic(self):
        approved = ProceduralRecord(
            strategy_name="approved_strategy",
            description="Validate approved node paths",
            status="trial",
        )
        deprecated = ProceduralRecord(
            strategy_name="deprecated_strategy",
            description="Validate obsolete node paths",
            status="trial",
        )
        self.store.add_procedural(approved)
        self.store.add_procedural(deprecated)

        self.assertTrue(self.store.transition_procedural_status(approved.id, "active"))
        self.assertTrue(self.store.transition_procedural_status(deprecated.id, "deprecated"))

        approved_saved = self.store.get_procedural(approved.id)
        deprecated_saved = self.store.get_procedural(deprecated.id)
        self.assertEqual(approved_saved.status, "active")
        self.assertGreater(approved_saved.validated_at, 0)
        self.assertEqual(deprecated_saved.status, "deprecated")
        self.assertEqual(deprecated_saved.validated_at, 0)
        self.assertEqual(
            [record.id for record, _score in self.store.search_procedural("node paths", top_k=10)],
            [approved.id],
        )

        self.assertFalse(self.store.transition_procedural_status(approved.id, "deprecated"))
        self.assertFalse(self.store.transition_procedural_status(deprecated.id, "active"))
        self.assertFalse(self.store.transition_procedural_status("missing", "active"))
        self.assertFalse(self.store.transition_procedural_status(approved.id, "unknown"))

    def test_deep_sleep_does_not_count_strategy_consolidation_as_usage(self):
        record = ProceduralRecord(
            strategy_name="validate_before_cook",
            description="Validate the node path before cooking",
        )
        self.store.add_procedural(record)
        reflection = ReflectionModule(store=self.store)
        client = FakeAIClient({
            "episodic_summary": "Validated the workflow.",
            "semantic_rules": [],
            "procedural_strategies": [{
                "name": record.strategy_name,
                "description": record.description,
                "conditions": ["Before cooking a node"],
            }],
            "key_facts": [],
        })

        result = reflection.deep_sleep(
            session_id="session-1",
            all_messages=[{"role": "user", "content": "Validate then cook"}],
            ai_client=client,
            model="test-model",
            provider="test-provider",
        )

        saved = self.store.get_procedural(record.id)
        self.assertTrue(result["success"])
        self.assertEqual(saved.usage_count, 0)
        self.assertEqual(saved.success_rate, 0.5)

    def test_deep_sleep_strategy_enters_trial_and_is_not_searchable(self):
        reflection = ReflectionModule(store=self.store)
        client = FakeAIClient({
            "episodic_summary": "Validated the workflow.",
            "semantic_rules": [],
            "procedural_strategies": [{
                "name": "validate_before_cook",
                "description": "Validate the node path before cooking",
                "conditions": ["Before cooking a node"],
            }],
            "key_facts": [],
        })

        result = reflection.deep_sleep(
            session_id="session-1",
            all_messages=[{"role": "user", "content": "Validate then cook"}],
            ai_client=client,
            model="test-model",
            provider="test-provider",
        )

        saved = self.store.get_procedural_by_name("validate_before_cook")
        self.assertEqual(saved.status, "trial")
        self.assertEqual(saved.origin, "deep_sleep")
        self.assertEqual(saved.source_episodes, [result["episodic_id"]])
        self.assertEqual(self.store.search_procedural("validate before cook"), [])

    def test_deep_sleep_applies_explicit_scope_to_derived_memories(self):
        reflection = ReflectionModule(store=self.store)
        client = FakeAIClient({
            "episodic_summary": "Validated the Houdini 21 workflow.",
            "semantic_rules": [{
                "rule": "Validate node paths before cooking",
                "category": "workflow",
                "abstraction_level": 2,
                "confidence": 0.8,
            }],
            "procedural_strategies": [{
                "name": "validate_h21_node_path",
                "description": "Validate the node path before cooking",
                "conditions": ["Before cooking a node"],
            }],
            "key_facts": [],
        })
        scope = {"houdini_version": "21.0", "project": "of3d"}

        reflection.deep_sleep(
            session_id="session-1",
            all_messages=[{"role": "user", "content": "Validate then cook"}],
            ai_client=client,
            model="test-model",
            provider="test-provider",
            memory_scope=scope,
        )

        row = self.store._conn.execute(
            "SELECT * FROM semantic_memory WHERE rule = ?",
            ("Validate node paths before cooking",),
        ).fetchone()
        semantic = self.store._row_to_semantic(row)
        procedural = self.store.get_procedural_by_name("validate_h21_node_path")
        self.assertEqual(semantic.scope, scope)
        self.assertEqual(procedural.scope, scope)


if __name__ == "__main__":
    unittest.main()