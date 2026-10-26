import json
from pathlib import Path
from unittest import mock

from houdini_agent.core.memory_mixin import MemoryMixin
from houdini_agent.utils.embedding import LocalEmbedder
from houdini_agent.utils.memory_store import MemoryStore, SemanticRecord


def recall_metrics(cases, retrieved, top_k=3):
    positives = hits = returned = unrelated = negative_queries = false_queries = 0
    recalls = precisions = 0.0
    for case, actual in zip(cases, retrieved):
        expected = set(case["expected"])
        actual = set(actual[:top_k])
        overlap = len(expected & actual)
        returned += len(actual)
        unrelated += len(actual - expected)
        precisions += overlap / top_k
        if expected:
            positives += 1
            hits += bool(overlap)
            recalls += overlap / len(expected)
        else:
            negative_queries += 1
            false_queries += bool(actual)
    return {
        "hit_rate": hits / positives if positives else 0.0,
        "precision_at_k": precisions / len(cases) if cases else 0.0,
        "recall_at_k": recalls / positives if positives else 0.0,
        "false_activation_rate": unrelated / returned if returned else 0.0,
        "negative_query_activation_rate": false_queries / negative_queries if negative_queries else 0.0,
    }


def test_metrics_distinguish_retrieval_quality_from_usage():
    metrics = recall_metrics([{"expected": ["good"]}, {"expected": []}], [["good", "bad"], ["wrong"]])
    assert metrics["hit_rate"] == 1.0
    assert metrics["recall_at_k"] == 1.0
    assert metrics["false_activation_rate"] == 2 / 3
    assert metrics["negative_query_activation_rate"] == 1.0
    assert recall_metrics([], [])["false_activation_rate"] == 0.0


def test_fallback_recall_quality_baseline(tmp_path):
    rows = [json.loads(line) for line in (Path(__file__).parent / "fixtures/memory_recall_eval.jsonl").read_text(encoding="utf-8").splitlines()]
    corpus, cases = rows[0], rows[1:]
    embedder = LocalEmbedder(cache_dir=tmp_path / "embeddings", load_semantic_model=False)
    store = MemoryStore(tmp_path / "memory.db", embedder)
    mixin = MemoryMixin()
    mixin._memory_store = store
    mixin._memory_initialized = True
    mixin._conversation_history = []
    mixin._username = "offline-eval"
    retrieved = []
    try:
        for memory in corpus["memories"]:
            store.add_semantic(SemanticRecord(**memory, confidence=0.8, abstraction_level=2))
        with mock.patch("houdini_agent.utils.team_memory_store.get_team_memory_store", side_effect=RuntimeError("offline")):
            for case in cases:
                mixin._activate_long_term_memory(case["query"])
                retrieved.append([item["record_id"] for item in (mixin._pending_memory_reinforcement or {}).values()])
        metrics = recall_metrics(cases, retrieved)
        print("MEMORY_RECALL_BASELINE " + json.dumps(metrics, sort_keys=True))
        assert len(cases) == 24 and not embedder.is_semantic
        assert metrics["hit_rate"] >= 1.0
        assert metrics["recall_at_k"] >= 1.0
        assert metrics["precision_at_k"] >= 0.25 - 1e-9
        assert metrics["false_activation_rate"] <= 0.75 + 1e-9
        assert metrics["negative_query_activation_rate"] <= 1.0
    finally:
        store.close()