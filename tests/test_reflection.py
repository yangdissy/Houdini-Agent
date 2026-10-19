import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from houdini_agent.utils.memory_store import MemoryStore
from houdini_agent.utils.reflection import DEEP_REFLECT_INTERVAL, ReflectionModule
from tests.test_team_memory import FakeEmbedder


class ErrorAIClient:
    def chat_stream(self, **_kwargs):
        yield {"type": "error", "error": "provider unavailable"}


class PayloadAIClient:
    def __init__(self, payload):
        self.payload = payload

    def chat_stream(self, **_kwargs):
        yield {"type": "content", "content": json.dumps(self.payload)}


class InvalidJSONAIClient:
    def chat_stream(self, **_kwargs):
        yield {"type": "content", "content": '{"semantic_rules": [}'}


class ReflectionTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.store = MemoryStore(
            db_path=Path(self.temp_dir.name) / "agent_memory.db",
            embedder=FakeEmbedder(),
        )

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_failed_deep_reflection_keeps_retry_schedule(self):
        reflection = ReflectionModule(store=self.store)
        reflection._task_count_since_reflect = DEEP_REFLECT_INTERVAL - 1

        result = reflection.reflect_on_task(
            session_id="session-1",
            task_description="Build a node network",
            result_summary="Completed",
            success=True,
            error_count=0,
            retry_count=0,
            tool_calls=[],
            ai_client=ErrorAIClient(),
            model="model",
            provider="provider",
        )

        self.assertFalse(result["deep_reflected"])
        self.assertEqual(
            reflection.get_reflection_stats()["tasks_since_reflect"],
            DEEP_REFLECT_INTERVAL,
        )

    def test_light_sleep_normalizes_model_generated_rules(self):
        reflection = ReflectionModule(store=self.store)
        client = PayloadAIClient({
            "episodic_summary": "Captured a reliable workflow.",
            "semantic_rules": [
                {
                    "rule": "Validate the node before cooking",
                    "category": "not-a-category",
                    "abstraction_level": "3",
                    "confidence": "4.5",
                },
                "invalid-entry",
            ],
            "key_facts": {"invalid": "container"},
        })

        result = reflection.light_sleep(
            "session-1",
            [{"role": "user", "content": "Remember this workflow"}],
            client,
            "model",
            "provider",
        )

        records = self.store.get_all_semantic()
        self.assertTrue(result["success"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].category, "general")
        self.assertEqual(records[0].abstraction_level, 3)
        self.assertEqual(records[0].confidence, 1.0)

    def test_message_budget_keeps_recent_context_in_order(self):
        messages = [
            {"role": "user", "content": "old-request"},
            {"role": "assistant", "content": "recent-answer"},
            {"role": "user", "content": "latest-request"},
        ]

        text = ReflectionModule._messages_to_text(messages, max_chars=65)

        self.assertNotIn("old-request", text)
        self.assertIn("recent-answer", text)
        self.assertIn("latest-request", text)
        self.assertLess(text.index("recent-answer"), text.index("latest-request"))
        self.assertTrue(text.startswith("... (更早的内容已省略)"))
        self.assertLessEqual(len(text), 65)

    def test_corrected_complex_success_reaches_strengthening_threshold(self):
        reflection = ReflectionModule(store=self.store)
        tool_calls = [
            {"name": "create_node", "success": False, "error": "invalid parameter"},
            {"name": "create_node", "success": True, "error": ""},
        ] + [
            {"name": "set_node_parameter", "success": True, "error": ""}
            for _ in range(86)
        ]

        result = reflection.reflect_on_task(
            session_id="session-1",
            task_description="Build a complex node network",
            result_summary="Validated node network created",
            success=True,
            error_count=4,
            retry_count=3,
            tool_calls=tool_calls,
        )

        self.assertIn("error_correction", result["tags"])
        self.assertGreaterEqual(
            result["reward"], reflection.reward_engine.strengthen_threshold
        )

    def test_invalid_deep_reflection_reports_parse_reason(self):
        reflection = ReflectionModule(store=self.store)

        result = reflection._parse_reflection_response(
            '{"semantic_rules": [}', []
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_json")

    def test_deep_reflection_parse_reason_reaches_task_result(self):
        reflection = ReflectionModule(store=self.store)
        reflection._task_count_since_reflect = DEEP_REFLECT_INTERVAL - 1

        result = reflection.reflect_on_task(
            session_id="session-1",
            task_description="Build a node network",
            result_summary="Completed",
            success=True,
            error_count=0,
            retry_count=0,
            tool_calls=[],
            ai_client=InvalidJSONAIClient(),
            model="model",
            provider="provider",
        )

        self.assertFalse(result["deep_reflected"])
        self.assertEqual(result["deep_reflection_error"], "invalid_json")

if __name__ == "__main__":
    unittest.main()