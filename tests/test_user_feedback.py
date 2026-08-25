# -*- coding: utf-8 -*-
"""用户手动反馈（👍/👎）修正 episodic reward 的测试。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from houdini_agent.utils.memory_store import MemoryStore, EpisodicRecord
from houdini_agent.utils.reward_engine import (
    RewardEngine,
    TAG_USER_PRAISED,
    TAG_USER_REJECTED,
)
from tests.test_team_memory import FakeEmbedder


def _make_episodic(store, task="test task", success=True, importance=1.0):
    rec = EpisodicRecord(
        session_id="s1",
        task_description=task,
        actions=[],
        result_summary="done",
        success=success,
        importance=importance,
    )
    store.add_episodic(rec)
    return rec


class ApplyUserFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.store = MemoryStore(
            db_path=Path(self.temp_dir.name) / "agent_memory.db",
            embedder=FakeEmbedder(),
        )
        self.engine = RewardEngine(store=self.store)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_praise_raises_reward_and_importance(self):
        rec = _make_episodic(self.store, importance=1.0)
        result = self.engine.apply_user_feedback(rec.id, positive=True)

        self.assertEqual(result["reward"], 0.85)
        self.assertGreater(result["importance"], 1.0)
        self.assertIn(TAG_USER_PRAISED, result["tags"])

        saved = self.store.get_episodic(rec.id)
        self.assertEqual(saved.reward_score, 0.85)
        self.assertIn(TAG_USER_PRAISED, saved.tags)

    def test_reject_lowers_reward_and_importance(self):
        rec = _make_episodic(self.store, importance=1.0)
        result = self.engine.apply_user_feedback(rec.id, positive=False)

        self.assertEqual(result["reward"], 0.15)
        self.assertLess(result["importance"], 1.0)
        self.assertIn(TAG_USER_REJECTED, result["tags"])

        saved = self.store.get_episodic(rec.id)
        self.assertEqual(saved.reward_score, 0.15)
        self.assertIn(TAG_USER_REJECTED, saved.tags)

    def test_feedback_on_missing_record_returns_error(self):
        result = self.engine.apply_user_feedback("nonexistent-id", positive=True)
        self.assertIn("error", result)

    def test_praise_caps_importance_at_max(self):
        rec = _make_episodic(self.store, importance=4.9)
        result = self.engine.apply_user_feedback(rec.id, positive=True)
        self.assertLessEqual(result["importance"], 5.0)


if __name__ == "__main__":
    unittest.main()
