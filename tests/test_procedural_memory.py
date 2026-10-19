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
        )
        self.store.add_procedural(record)

        self.store.update_procedural_usage(record.id, success=True)
        self.store.update_procedural_usage(record.id, success=False)

        saved = self.store.get_procedural(record.id)
        self.assertEqual(saved.usage_count, 2)
        self.assertAlmostEqual(saved.success_rate, 0.5)
        self.assertGreaterEqual(saved.last_used, record.last_used)

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


if __name__ == "__main__":
    unittest.main()