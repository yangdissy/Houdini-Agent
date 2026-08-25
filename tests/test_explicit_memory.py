import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from houdini_agent.utils.explicit_memory import ExplicitMemoryService
from houdini_agent.utils.memory_store import MemoryStore
from tests.test_team_memory import FakeEmbedder


class ExplicitMemoryServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.store = MemoryStore(
            db_path=Path(self.temp_dir.name) / "agent_memory.db",
            embedder=FakeEmbedder(),
        )
        self.service = ExplicitMemoryService(self.store)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_creates_and_verifies_memory(self):
        result = self.service.remember("始终使用中文回答")

        self.assertEqual(result.status, "created")
        saved = self.store.get_semantic(result.memory_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.rule, "始终使用中文回答")
        self.assertEqual(saved.category, "preference")
        self.assertEqual(saved.abstraction_level, 0)

    def test_duplicate_is_idempotent(self):
        first = self.service.remember("始终使用中文回答")
        second = self.service.remember("始终使用中文回答")

        self.assertEqual(first.status, "created")
        self.assertEqual(second.status, "already_exists")
        self.assertEqual(first.memory_id, second.memory_id)
        self.assertEqual(self.store.count_semantic(), 1)

    def test_rejects_credentials(self):
        result = self.service.remember("api_key = secret-value")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(self.store.count_semantic(), 0)

    def test_rejects_empty_and_oversized_content(self):
        self.assertEqual(self.service.remember(" ").status, "rejected")
        self.assertEqual(self.service.remember("x" * 2001).status, "rejected")

    def test_save_intent_is_required_for_write_tool(self):
        self.assertTrue(self.service.has_explicit_save_intent("请记住始终使用中文回答"))
        self.assertFalse(self.service.has_explicit_save_intent("你还记得我的偏好吗"))

    def test_save_intent_rejects_negated_mentions(self):
        # 否定/抱怨语境中提到“记住/remember”不应触发放行（fail-closed）
        self.assertFalse(self.service.has_explicit_save_intent("我根本记不住你说的话"))
        self.assertFalse(self.service.has_explicit_save_intent("这个不用记住，临时用一下"))
        self.assertFalse(self.service.has_explicit_save_intent("别记住我的密码"))
        self.assertFalse(self.service.has_explicit_save_intent("please do not remember this"))
        # 正常保存请求不受影响
        self.assertTrue(self.service.has_explicit_save_intent("记住：以后都按中文回答"))

    def test_already_exists_message_includes_existing_rule(self):
        self.service.remember("始终使用中文回答")
        result = self.service.remember("始终使用中文回答")
        self.assertEqual(result.status, "already_exists")
        self.assertIn("始终使用中文回答", result.message)

    def test_created_memory_is_searchable_after_reopen(self):
        result = self.service.remember("始终使用中文回答")
        self.assertEqual(result.status, "created")
        self.store.close()

        reopened = MemoryStore(
            db_path=Path(self.temp_dir.name) / "agent_memory.db",
            embedder=FakeEmbedder(),
        )
        try:
            hits = reopened.search_all_levels("始终使用中文", top_k=5, min_confidence=0.0)
            self.assertTrue(any(rec.rule == "始终使用中文回答" for rec, _score in hits))
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
