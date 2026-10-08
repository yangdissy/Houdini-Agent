import unittest
from unittest import mock

from houdini_agent.core.memory_mixin import MemoryMixin
from houdini_agent.utils.memory_activation import (
    MemoryActivationCandidate,
    MemoryActivationSelector,
)
from houdini_agent.utils.memory_store import EpisodicRecord, SemanticRecord
from houdini_agent.utils.team_memory_store import TeamSemanticRecord


class MemoryActivationSelectorTest(unittest.TestCase):
    def test_prefers_high_confidence_priority_adjusted_score(self):
        selector = MemoryActivationSelector(max_chars=500)

        selected = selector.select([
            MemoryActivationCandidate("semantic", "weak raw match", score=0.60, priority=0.2, confidence=0.2),
            MemoryActivationCandidate("semantic", "trusted preference", score=0.50, priority=1.2, confidence=0.9),
        ])

        self.assertEqual(selected[0].text, "trusted preference")

    def test_removes_redundant_memory_lines(self):
        selector = MemoryActivationSelector(max_chars=500)

        selected = selector.select([
            MemoryActivationCandidate(
                "semantic",
                "[L2 Rule] (conf=0.90) Always validate Houdini node path before cooking",
                score=0.9,
                priority=1.0,
                confidence=0.9,
            ),
            MemoryActivationCandidate(
                "episodic",
                "[Past Experience] Always validate Houdini node path before cooking",
                score=0.8,
                priority=1.0,
                confidence=0.8,
            ),
        ])

        self.assertEqual(len(selected), 1)

    def test_respects_prompt_budget_without_dropping_first_candidate(self):
        selector = MemoryActivationSelector(max_chars=45)

        selected = selector.select([
            MemoryActivationCandidate("semantic", "first candidate is allowed even when long", score=0.9),
            MemoryActivationCandidate("semantic", "second candidate should not fit", score=0.8),
        ])

        self.assertEqual([item.text for item in selected], ["first candidate is allowed even when long"])


class FakeEmbedder:
    is_semantic = False


class FakeMemoryStore:
    def __init__(self):
        self.embedder = FakeEmbedder()
        self.semantic_activations = []
        self.episodic_updates = []

    def search_by_level(self, query, level, top_k=3, threshold=0.0):
        if level == 1:
            return [(SemanticRecord(id="s1", rule="Always validate Houdini node path before cooking", confidence=0.9), 0.6)]
        if level == 2:
            return [(SemanticRecord(id="s2", rule="Always validate Houdini node path before cooking", confidence=0.8), 0.55)]
        return []

    def search_episodic(self, query, top_k=2, min_importance=0.3):
        return [(
            EpisodicRecord(
                id="e1",
                task_description="Validate Houdini node path before cooking",
                result_summary="Cook succeeded after validation",
                success=True,
                importance=1.0,
            ),
            0.2,
        )]

    def search_procedural(self, query, top_k=2):
        return []

    def increment_semantic_activation(self, record_id):
        self.semantic_activations.append(record_id)

    def update_episodic_importance(self, record_id, new_importance):
        self.episodic_updates.append((record_id, new_importance))


class FakeTeamMemoryStore:
    def search_semantic(self, query, top_k=3):
        return [(
            TeamSemanticRecord(
                id="ts1",
                rule="Check File Cache Load from Disk before debugging viewport differences",
                category="debug",
                abstraction_level=2,
                confidence=0.9,
                source_users=["alice", "bob"],
            ),
            0.5,
        )]


class MemoryMixinActivationTest(unittest.TestCase):
    def test_activate_long_term_memory_selects_diverse_candidates(self):
        mixin = MemoryMixin()
        mixin._memory_initialized = True
        mixin._memory_store = FakeMemoryStore()

        with mock.patch(
            "houdini_agent.utils.team_memory_store.get_team_memory_store",
            side_effect=RuntimeError("team unavailable"),
        ):
            result = mixin._activate_long_term_memory("cook node")

        self.assertIn("[Long-Term Memory", result)
        self.assertIn("Always validate Houdini node path", result)
        self.assertEqual(result.count("Always validate Houdini node path"), 1)
        self.assertEqual(mixin._memory_store.semantic_activations, [])
        self.assertEqual(mixin._memory_store.episodic_updates, [])
        self.assertEqual(
            mixin._pending_memory_reinforcement,
            {"semantic_ids": ["s1"], "episodic": [("e1", 1.0)]},
        )

    def test_positive_task_result_reinforces_pending_memories(self):
        mixin = MemoryMixin()
        mixin._memory_store = FakeMemoryStore()
        mixin._pending_memory_reinforcement = {
            "semantic_ids": ["s1"],
            "episodic": [("e1", 1.0)],
        }

        mixin._reinforce_pending_memories(0.5)

        self.assertEqual(mixin._memory_store.semantic_activations, ["s1"])
        self.assertEqual(mixin._memory_store.episodic_updates, [("e1", 1.05)])
        self.assertIsNone(mixin._pending_memory_reinforcement)

    def test_non_positive_task_result_discards_pending_memories(self):
        mixin = MemoryMixin()
        mixin._memory_store = FakeMemoryStore()
        mixin._pending_memory_reinforcement = {
            "semantic_ids": ["s1"],
            "episodic": [("e1", 1.0)],
        }

        mixin._reinforce_pending_memories(0.0)

        self.assertEqual(mixin._memory_store.semantic_activations, [])
        self.assertEqual(mixin._memory_store.episodic_updates, [])
        self.assertIsNone(mixin._pending_memory_reinforcement)

    def test_memory_query_includes_previous_user_goal(self):
        mixin = MemoryMixin()
        mixin._conversation_history = [
            {"role": "user", "content": "Create a pyro cache with checkpointing"},
            {"role": "assistant", "content": "I created the initial network."},
        ]

        query = mixin._build_memory_query("Continue with the previous setup", {})

        self.assertIn("Continue with the previous setup", query)
        self.assertIn("Create a pyro cache with checkpointing", query)

    def test_new_activation_clears_stale_pending_reinforcement(self):
        mixin = MemoryMixin()
        mixin._memory_initialized = False
        mixin._memory_store = None
        mixin._pending_memory_reinforcement = {"semantic_ids": ["stale"]}

        self.assertEqual(mixin._activate_long_term_memory("new task"), "")
        self.assertIsNone(mixin._pending_memory_reinforcement)

    def test_activate_long_term_memory_includes_relevant_team_memory(self):
        mixin = MemoryMixin()
        mixin._memory_initialized = True
        mixin._memory_store = FakeMemoryStore()

        with mock.patch(
            "houdini_agent.utils.team_memory_store.get_team_memory_store",
            return_value=FakeTeamMemoryStore(),
        ):
            result = mixin._activate_long_term_memory("File Cache viewport difference")

        self.assertIn("[Team Memory]", result)
        self.assertIn("alice, bob", result)


if __name__ == "__main__":
    unittest.main()
