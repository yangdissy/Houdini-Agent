import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from houdini_agent.utils.memory_store import EpisodicRecord, MemoryStore, SemanticRecord
from houdini_agent.utils.reflection import ReflectionModule
from tests.test_team_memory import FakeEmbedder


class FakeAIClient:
    def __init__(self, payload):
        self.payload = payload

    def chat_stream(self, **_kwargs):
        yield {"type": "content", "content": json.dumps(self.payload)}


class SemanticMemoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.store = MemoryStore(
            db_path=Path(self.temp_dir.name) / "agent_memory.db",
            embedder=FakeEmbedder(),
        )

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_upsert_duplicate_merges_episode_sources_and_reinforces_rule(self):
        first, created = self.store.upsert_semantic(
            SemanticRecord(
                rule="Validate the node path before cooking",
                source_episodes=["episode-1"],
                confidence=0.6,
                category="debug",
            ),
            confidence_increment=0.1,
        )
        second, created_again = self.store.upsert_semantic(
            SemanticRecord(
                rule="Validate the node path before cooking",
                source_episodes=["episode-2", "episode-1"],
                confidence=0.8,
                category="debug",
            ),
            confidence_increment=0.1,
        )

        saved = self.store.get_semantic(first.id)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(second.id, first.id)
        self.assertEqual(self.store.count_semantic(), 1)
        self.assertEqual(saved.source_episodes, ["episode-1", "episode-2"])
        self.assertAlmostEqual(saved.confidence, 0.7)
        self.assertEqual(saved.activation_count, 1)

    def test_light_sleep_links_rules_to_summary_episodes(self):
        reflection = ReflectionModule(store=self.store)
        client = FakeAIClient({
            "episodic_summary": "Validated the node before cooking.",
            "semantic_rules": [{
                "rule": "Validate the node path before cooking",
                "category": "debug",
                "abstraction_level": 2,
                "confidence": 0.7,
            }],
            "key_facts": [],
        })
        messages = [{"role": "user", "content": "Validate then cook"}]

        first = reflection.light_sleep("session-1", messages, client, "model", "provider")
        second = reflection.light_sleep("session-1", messages, client, "model", "provider")

        saved = self.store.get_all_semantic()[0]
        self.assertEqual(self.store.count_semantic(), 1)
        self.assertEqual(saved.source_episodes, [first["episodic_id"], second["episodic_id"]])
        self.assertEqual(saved.activation_count, 1)

    def test_deep_sleep_links_rules_and_key_facts_to_summary_episode(self):
        reflection = ReflectionModule(store=self.store)
        client = FakeAIClient({
            "episodic_summary": "Captured the complete workflow.",
            "semantic_rules": [{
                "rule": "Validate the node path before cooking",
                "category": "debug",
                "abstraction_level": 2,
                "confidence": 0.8,
            }],
            "procedural_strategies": [],
            "key_facts": ["用户始终使用中文回复"],
        })

        result = reflection.deep_sleep(
            "session-1",
            [{"role": "user", "content": "Capture this workflow"}],
            client,
            "model",
            "provider",
        )

        records = self.store.get_all_semantic()
        self.assertEqual(len(records), 2)
        self.assertTrue(all(
            record.source_episodes == [result["episodic_id"]]
            for record in records
        ))

    def test_task_reflection_merges_new_episode_sources(self):
        reflection = ReflectionModule(store=self.store)
        first_episode = EpisodicRecord(id="episode-1")
        second_episode = EpisodicRecord(id="episode-2")
        response = json.dumps({
            "semantic_rules": [{
                "rule": "Validate the node path before cooking",
                "category": "debug",
                "abstraction_level": 2,
                "confidence": 0.7,
            }],
            "strategy_updates": [],
            "skill_confidence": {},
        })

        reflection._parse_reflection_response(response, [first_episode])
        reflection._parse_reflection_response(response, [second_episode])

        saved = self.store.get_all_semantic()[0]
        self.assertEqual(self.store.count_semantic(), 1)
        self.assertEqual(saved.source_episodes, ["episode-1", "episode-2"])
        self.assertEqual(saved.activation_count, 1)

    def test_rule_reflect_does_not_write_before_episode_is_inserted(self):
        reflection = ReflectionModule(store=self.store)
        episode = EpisodicRecord(success=False, retry_count=3)

        with mock.patch.object(self.store, "update_episodic_tags") as update_tags:
            reflected = reflection.rule_reflect(
                episode,
                [{"name": "cook", "success": False, "error": "failed"}],
            )

        self.assertIn("retry_heavy", reflected.tags)
        update_tags.assert_not_called()


if __name__ == "__main__":
    unittest.main()