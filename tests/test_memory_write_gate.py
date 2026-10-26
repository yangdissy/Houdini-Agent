import json
from unittest import mock

import pytest

from houdini_agent.utils.embedding import LocalEmbedder
from houdini_agent.utils.memory_store import EpisodicRecord, MemoryStore, SemanticRecord
from houdini_agent.core.memory_mixin import MemoryMixin


@pytest.fixture
def store(tmp_path):
    memory = MemoryStore(tmp_path / "memory.db", LocalEmbedder(cache_dir=tmp_path / "emb", load_semantic_model=False))
    yield memory
    memory.close()


def test_automatic_rules_need_real_evidence_and_enter_trial(store):
    missing, created = store.upsert_semantic(SemanticRecord(rule="Validate node paths before cooking"), source="reflection")
    assert not created and store.get_semantic(missing.id) is None
    episode = EpisodicRecord(task_description="Cook a node")
    store.add_episodic(episode)
    record, created = store.upsert_semantic(SemanticRecord(
        rule="Validate node paths before cooking", confidence=0.95, source_episodes=[episode.id], abstraction_level=0,
    ), source="reflection")
    assert created and record.status == "trial" and record.confidence == 0.5
    assert record.abstraction_level == 1
    duplicate, created = store.upsert_semantic(SemanticRecord(
        rule=record.rule, source_episodes=[episode.id], abstraction_level=1,
    ), source="reflection")
    assert not created and duplicate.confidence == 0.5 and duplicate.activation_count == 0
    for _ in range(2):
        store.settle_semantic_usage(record.id, True, 0.5)
    assert store.get_semantic(record.id).status == "trial"
    store.settle_semantic_usage(record.id, True, 0.5)
    promoted = store.get_semantic(record.id)
    assert promoted.status == "active" and promoted.cited_count == 3 and promoted.confidence > 0.5


@pytest.mark.parametrize("text,reason", [("tiny", "length"), ("password = abc123", "sensitive_or_control"), ("always be helpful", "generic")])
def test_bad_rules_are_rejected_with_reason(store, text, reason):
    record, created = store.upsert_semantic(SemanticRecord(rule=text), source="deep_sleep")
    assert not created and store.get_semantic(record.id) is None
    events = [json.loads(line) for line in (store.db_path.parent / "audit/memory_write.jsonl").read_text().splitlines()]
    assert events[-1]["reason"] == reason
    assert text not in json.dumps(events)


def test_unused_decays_but_nonpositive_citation_does_not_promote(store):
    record = SemanticRecord(rule="Validate node paths before cooking", confidence=0.5, status="trial")
    store.add_semantic(record)
    store.settle_semantic_usage(record.id, False, 0.8)
    assert store.get_semantic(record.id).confidence == pytest.approx(0.485)
    store.settle_semantic_usage(record.id, True, 0.0)
    assert store.get_semantic(record.id).cited_count == 0


def test_audit_failure_denies_automatic_write(store):
    with mock.patch("houdini_agent.utils.memory_store.append_quality_audit", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.upsert_semantic(SemanticRecord(rule="Validate node paths before cooking"), source="reflection")
    assert store.count_semantic() == 0


def test_stats_exclude_unknown_and_break_down_layers(store):
    pending = {"M1": {"kind": "semantic", "record_id": "s1", "layer": 2, "score": 0.8},
               "M2": {"kind": "team_semantic", "record_id": "ts1", "layer": 2, "score": 0.7}}
    store.record_recall(pending, {"M1"}, "test-session", 0.5)
    store.record_recall(pending, None, "test-session", 0.5)
    stats = store.get_quality_stats()
    assert stats["unknown_rate"] == 0.5
    assert stats["groups"]["all"]["declared_use_rate"] == 0.5
    assert stats["groups"]["all"]["known"] == 2
    assert stats["groups"]["semantic"]["declared_use_rate"] == 1.0
    assert stats["groups"]["team_semantic"]["uncited_rate"] == 1.0
    assert stats["groups"]["L2"]["injected"] == 4


def test_no_samples_are_not_zero_percent(store):
    assert store.get_quality_stats()["unknown_rate"] is None
    store.record_recall({"M1": {"kind": "semantic", "record_id": "s1", "layer": 1}}, None, "test", 0.0)
    assert store.get_quality_stats()["groups"]["all"]["declared_use_rate"] is None


def test_trial_rules_cannot_be_shared_with_team(store):
    from houdini_agent.utils.team_memory_export import build_team_export_payload
    store.add_semantic(SemanticRecord(rule="Check point attributes before copying geometry", status="trial", confidence=0.5))
    assert build_team_export_payload(store)["semantic"] == []


def test_real_store_settlement_only_rewards_cited_memories(store):
    first = SemanticRecord(rule="Verify point attributes before copying geometry", confidence=0.5, status="trial")
    second = SemanticRecord(rule="Check cache paths before writing files", confidence=0.5, status="trial")
    store.add_semantic(first)
    store.add_semantic(second)
    episode = EpisodicRecord(task_description="Generate geometry", importance=1.0)
    store.add_episodic(episode)
    mixin = MemoryMixin()
    mixin._memory_store = store
    mixin._pending_memory_reinforcement = {
        "M1": {"kind": "semantic", "record_id": first.id, "layer": 2},
        "M2": {"kind": "semantic", "record_id": second.id, "layer": 2},
        "M3": {"kind": "episodic", "record_id": episode.id, "layer": None},
        "M4": {"kind": "team_semantic", "record_id": "shared", "layer": 2},
    }
    mixin._reinforce_pending_memories(0.8, True, "Done\n[mem-used: M1,M4]", session_id="test")
    assert store.get_semantic(first.id).cited_count == 1
    assert store.get_semantic(second.id).cited_count == 0
    assert store.get_semantic(second.id).confidence == pytest.approx(0.485)
    assert store.get_episodic(episode.id).importance == pytest.approx(0.97)
    assert mixin._pending_memory_reinforcement is None
    assert store.get_quality_stats()["groups"]["all"]["declared_use_rate"] == 0.5


def test_unknown_completion_never_penalizes_memory(store):
    record = SemanticRecord(rule="Verify node types before connecting geometry", confidence=0.5)
    store.add_semantic(record)
    mixin = MemoryMixin()
    mixin._memory_store = store
    mixin._pending_memory_reinforcement = {"M1": {"kind": "semantic", "record_id": record.id, "layer": 2}}
    mixin._record_unknown_memory_recall()
    assert store.get_semantic(record.id).confidence == 0.5
    assert store.get_quality_stats()["unknown_rate"] == 1.0


def test_background_reflection_uses_its_snapshot_not_next_round(store):
    record = SemanticRecord(rule="Verify node types before connecting geometry", confidence=0.5, status="trial")
    store.add_semantic(record)
    mixin = MemoryMixin()
    mixin._memory_store = store
    mixin._memory_initialized = True
    mixin._agent_history = []
    mixin._conversation_history = []
    mixin._agent_session_id = mixin._session_id = "new-session"
    mixin._growth_tracker = None
    mixin.client = mock.Mock()
    mixin._pending_memory_reinforcement = {"M1": {"kind": "semantic", "record_id": "next-round", "layer": 2}}
    mixin._reflection_module = mock.Mock()
    mixin._reflection_module.reflect_on_task.return_value = {"reward": 0.8}
    mixin._reflect_after_task({
        "ok": True, "final_content": "Done\n[mem-used: M1]", "_memory_session_id": "old-session",
        "_memory_recall": {"M1": {"kind": "semantic", "record_id": record.id, "layer": 2}},
    }, {"user_message": "Old task"})
    assert store.get_semantic(record.id).cited_count == 1
    assert mixin._pending_memory_reinforcement["M1"]["record_id"] == "next-round"
    arguments = mixin._reflection_module.reflect_on_task.call_args.kwargs
    assert arguments["session_id"] == "old-session" and arguments["task_description"] == "Old task"
    assert "mem-used" not in arguments["result_summary"]


def test_time_decay_cannot_increase_low_trial_confidence(store):
    record = SemanticRecord(rule="Verify node types before connecting geometry", confidence=0.1, status="trial", abstraction_level=1)
    store.add_semantic(record)
    store.decay_semantic_confidence()
    assert store.get_semantic(record.id).confidence <= 0.1