import unittest
from unittest import mock

from houdini_agent.core.memory_mixin import MemoryMixin
from houdini_agent.utils.memory_activation import (
    MemoryActivationCandidate,
    MemoryActivationSelector,
    parse_memory_usage,
    strip_memory_usage,
)
from houdini_agent.utils.memory_store import EpisodicRecord, ProceduralRecord, SemanticRecord
from houdini_agent.utils.team_memory_store import TeamSemanticRecord


class MemoryActivationSelectorTest(unittest.TestCase):
    def test_usage_declaration_requires_known_unique_aliases_at_end(self):
        self.assertEqual(parse_memory_usage("Done\n[mem-used: M1,M3]", ["M1", "M3"]), {"M1", "M3"})
        self.assertEqual(parse_memory_usage("Done\n[mem-used: none]", ["M1"]), set())
        for text in ("Done", "[mem-used: M2]", "[mem-used: M1,M1]",
                     "[mem-used: M1]\nMore", "[mem-used: M1]\n[mem-used: none]",
                     "<think>[mem-used: M1]</think>", "[mem-used: ]"):
            with self.subTest(text=text):
                self.assertIsNone(parse_memory_usage(text, ["M1"]))

    def test_strip_usage_preserves_answer(self):
        self.assertEqual(strip_memory_usage("Done\n[mem-used: M1]"), "Done\n")
        self.assertEqual(strip_memory_usage("ordinary [M1] reference"), "ordinary [M1] reference")
        declaration = "[mem-used: M1]"
        for end in range(1, len(declaration) + 1):
            self.assertEqual(strip_memory_usage("Done\n" + declaration[:end], streaming=True), "Done\n")

    def test_ui_uses_same_cleaning_for_history_and_copy(self):
        from tests.test_import_smoke import _install_qt_stubs, _install_thirdparty_stubs
        _install_thirdparty_stubs()
        _install_qt_stubs()
        from houdini_agent.ui.cursor_chat_widgets import AIResponse
        self.assertEqual(AIResponse._clean_content("Done\n[mem-used: M1]"), "Done")

    def test_request_retention_uses_available_content_extractor(self):
        from tests.test_import_smoke import _install_qt_stubs, _install_thirdparty_stubs
        _install_thirdparty_stubs()
        _install_qt_stubs()
        from houdini_agent.core.send_orchestrator_mixin import message_content_text
        block = "[Long-Term Memory]\n[M1] Validate before cooking"
        self.assertIn(block, message_content_text([{"type": "text", "text": block}]))
        self.assertNotIn(block, message_content_text("[M1] old history reference"))

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
        self.procedural_updates = []
        self.quality_policy = {"unused_decay": 0.97}
        self.recall_events = []

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
        if "cook node" not in query:
            return []
        return [(
            ProceduralRecord(
                id="p1",
                strategy_name="validate_before_cook",
                description="Validate the node path before cooking",
                priority=0.8,
                success_rate=0.75,
            ),
            0.5,
        )]

    def increment_semantic_activation(self, record_id):
        self.semantic_activations.append(record_id)

    def record_recall(self, pending, cited, session_id, reward):
        self.recall_events.append((pending, cited, session_id, reward))

    def settle_semantic_usage(self, record_id, cited, reward):
        if cited and reward > 0:
            self.semantic_activations.append(record_id)

    def get_episodic(self, record_id):
        return EpisodicRecord(id=record_id, importance=1.0)

    def update_episodic_importance(self, record_id, new_importance):
        self.episodic_updates.append((record_id, new_importance))

    def update_procedural_usage(self, record_id, success):
        self.procedural_updates.append((record_id, success))


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
        self.assertEqual({item['record_id'] for item in mixin._pending_memory_reinforcement.values()}, {'s1', 'e1', 'p1'})
        self.assertIn('[M1]', result)

    def test_positive_task_result_reinforces_pending_memories(self):
        mixin = MemoryMixin()
        mixin._memory_store = FakeMemoryStore()
        mixin._pending_memory_reinforcement = {
            "M1": {"kind": "semantic", "record_id": "s1"},
            "M2": {"kind": "episodic", "record_id": "e1"},
        }

        mixin._reinforce_pending_memories(0.5, task_success=True, final_content="Done\n[mem-used: M1,M2]")

        self.assertEqual(mixin._memory_store.semantic_activations, ["s1"])
        self.assertEqual(mixin._memory_store.episodic_updates, [("e1", 1.05)])
        self.assertIsNone(mixin._pending_memory_reinforcement)

    def test_task_outcome_updates_selected_procedural_memory(self):
        mixin = MemoryMixin()
        mixin._memory_store = FakeMemoryStore()
        mixin._pending_memory_reinforcement = {
            "M1": {"kind": "procedural", "record_id": "p1"},
        }

        mixin._reinforce_pending_memories(0.0, task_success=False, final_content="Done\n[mem-used: M1]")

        self.assertEqual(mixin._memory_store.semantic_activations, [])
        self.assertEqual(mixin._memory_store.episodic_updates, [])
        self.assertEqual(mixin._memory_store.procedural_updates, [("p1", False)])
        self.assertIsNone(mixin._pending_memory_reinforcement)

    def test_non_positive_task_result_discards_pending_memories(self):
        mixin = MemoryMixin()
        mixin._memory_store = FakeMemoryStore()
        mixin._pending_memory_reinforcement = {
            "M1": {"kind": "semantic", "record_id": "s1"},
            "M2": {"kind": "episodic", "record_id": "e1"},
        }

        mixin._reinforce_pending_memories(0.0)

        self.assertEqual(mixin._memory_store.semantic_activations, [])
        self.assertEqual(mixin._memory_store.episodic_updates, [])
        self.assertEqual(mixin._memory_store.procedural_updates, [])
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
        mixin._username = "tester"
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
