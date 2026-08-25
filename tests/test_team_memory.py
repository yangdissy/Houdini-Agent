# -*- coding: utf-8 -*-
"""Team memory sharing: export eligibility, opt-out toggle, and rebuild/dedup tests."""

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from houdini_agent.utils.memory_store import MemoryStore, SemanticRecord, ProceduralRecord
from houdini_agent.utils.team_memory_export import (
    build_team_export_payload,
    export_team_memory,
)
from houdini_agent.utils.team_memory_document import (
    MAX_EXPORT_FILE_BYTES,
    parse_team_export_file,
)
from houdini_agent.utils.team_memory_settings import (
    is_team_export_enabled,
    set_team_export_enabled,
)
from houdini_agent.utils.team_memory_store import TeamMemoryStore, rebuild_team_memory


class FakeEmbedder:
    def __init__(self, backend="fake", model_name="fake-model", dim=4):
        self._backend = backend
        self.model_name = model_name
        self.dim = dim
        self.is_semantic = backend != "fallback"
        self.encoded_texts = []

    def encode(self, text):
        self.encoded_texts.append(text)
        return _vec(float(len(text) or 1), 1.0, 0.0, 0.0)[:self.dim]

    @staticmethod
    def to_bytes(vector):
        return vector.astype("float32").tobytes()

    @staticmethod
    def from_bytes(data):
        import numpy as np
        return np.frombuffer(data, dtype=np.float32).copy()

    @staticmethod
    def cosine_similarity(left, right):
        from houdini_agent.utils.embedding import LocalEmbedder
        return LocalEmbedder.cosine_similarity(left, right)


def _vec(*values):
    """构造一个 4 维测试向量并归一化，方便手工控制余弦相似度。"""
    import numpy as np
    arr = np.array(list(values) + [0.0] * max(0, 4 - len(values)), dtype=np.float32)
    norm = np.linalg.norm(arr)
    return arr / norm if norm > 0 else arr


class BuildTeamExportPayloadTest(unittest.TestCase):
    def _store(self, temp_dir: str) -> MemoryStore:
        return MemoryStore(db_path=Path(temp_dir) / "agent_memory.db")

    def test_only_eligible_category_and_level_and_confidence_are_exported(self):
        with TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)

            # 应导出：技术类 + L2 + 高置信度
            store.add_semantic(SemanticRecord(
                rule="cook 前先检查 update mode", category="pitfall",
                abstraction_level=2, confidence=0.8,
            ))
            # 不应导出：preference 分类（个人偏好）
            store.add_semantic(SemanticRecord(
                rule="喜欢用中文回复", category="preference",
                abstraction_level=2, confidence=0.9,
            ))
            # 不应导出：L1 核心偏好层级
            store.add_semantic(SemanticRecord(
                rule="核心偏好条目", category="workflow",
                abstraction_level=1, confidence=0.9,
            ))
            # 不应导出：置信度不足
            store.add_semantic(SemanticRecord(
                rule="低置信度经验", category="knowledge",
                abstraction_level=2, confidence=0.2,
            ))
            # 不应导出：L5 原始细节
            store.add_semantic(SemanticRecord(
                rule="原始对话片段", category="debug",
                abstraction_level=5, confidence=0.9,
            ))

            # procedural: 应导出（用够、成功率够）
            store.add_procedural(ProceduralRecord(
                strategy_name="verify_before_modify", description="改前先查",
                priority=0.6, success_rate=0.8, usage_count=5,
            ))
            # procedural: 不应导出（usage_count 不足）
            store.add_procedural(ProceduralRecord(
                strategy_name="untested_strategy", description="没验证过",
                priority=0.6, success_rate=0.9, usage_count=1,
            ))

            payload = build_team_export_payload(store)
            store.close()

            semantic_rules = {e["rule"] for e in payload["semantic"]}
            self.assertEqual(semantic_rules, {"cook 前先检查 update mode"})

            procedural_names = {e["strategy_name"] for e in payload["procedural"]}
            self.assertEqual(procedural_names, {"verify_before_modify"})

            # embedding 序列化为 list，且带上后端标签
            self.assertIsInstance(payload["semantic"][0]["embedding"], list)
            self.assertIn("embedding_backend", payload["semantic"][0])
            self.assertEqual(payload["semantic"][0]["embedding_model"], store.embedder.model_name)
            self.assertEqual(payload["semantic"][0]["embedding_dimension"], store.embedder.dim)
            self.assertEqual(payload["semantic"][0]["embedding_format_version"], 1)
            store.close()


class ExportTeamMemoryToggleTest(unittest.TestCase):
    def test_export_skipped_when_disabled_and_written_when_enabled(self):
        with TemporaryDirectory() as repo_root, TemporaryDirectory() as store_dir:
            store = MemoryStore(db_path=Path(store_dir) / "agent_memory.db")
            store.add_semantic(SemanticRecord(
                rule="导出测试规则", category="workflow",
                abstraction_level=3, confidence=0.7,
            ))

            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root):
                username = "team_export_tester"

                set_team_export_enabled(username, False)
                self.assertFalse(is_team_export_enabled(username))
                self.assertIsNone(export_team_memory(username, store))

                set_team_export_enabled(username, True)
                self.assertTrue(is_team_export_enabled(username))
                export_path = export_team_memory(username, store)
                self.assertIsNotNone(export_path)
                self.assertTrue(export_path.exists())

                data = json.loads(export_path.read_text(encoding="utf-8"))
                self.assertEqual(data["username"], username)
                self.assertEqual(len(data["semantic"]), 1)

            store.close()

    def test_toggle_survives_repeated_enable_disable_cycles(self):
        """回归：确保开关可以来回切换多次（此前网络盘 replace 偶发失败会导致
        第二次切换被静默丢弃，见 team_memory_sharing_feature.md 记忆记录）。"""
        with TemporaryDirectory() as repo_root:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root):
                username = "toggle_cycle_tester"
                for expected in (False, True, False, True, True, False):
                    set_team_export_enabled(username, expected)
                    self.assertEqual(is_team_export_enabled(username), expected)

    def test_save_falls_back_to_direct_write_when_atomic_replace_keeps_failing(self):
        """模拟网络盘 rename-replace 反复失败：应退化为直写而不是静默丢弃设置。"""
        with TemporaryDirectory() as repo_root:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root):
                username = "replace_failure_tester"
                set_team_export_enabled(username, True)  # 先创建出已存在的目标文件

                from pathlib import Path as _Path
                with mock.patch.object(_Path, "replace", side_effect=OSError("simulated SMB lock")):
                    set_team_export_enabled(username, False)

                self.assertFalse(is_team_export_enabled(username))


class RebuildTeamMemoryTest(unittest.TestCase):
    def _write_export(self, temp_dir: str, username: str, payload: dict) -> Path:
        user_memory_dir = Path(temp_dir) / username / "memory"
        user_memory_dir.mkdir(parents=True, exist_ok=True)
        path = user_memory_dir / "team_export.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    @staticmethod
    def _v1_payload(username: str, semantic=None, procedural=None) -> dict:
        return {
            "schema_version": 1,
            "username": username,
            "exported_at": 1.0,
            "semantic": semantic or [],
            "procedural": procedural or [],
        }

    @staticmethod
    def _with_provenance(entry: dict) -> dict:
        result = dict(entry)
        result.update({
            "embedding_model": "fallback-model",
            "embedding_dimension": len(result["embedding"]),
            "embedding_format_version": 1,
        })
        return result

    def test_rebuild_dedupes_similar_entries_and_unions_contributors(self):
        with TemporaryDirectory() as temp_dir, TemporaryDirectory() as db_dir:
            same_vec = _vec(1.0, 0.0, 0.0, 0.0).tolist()
            different_vec = _vec(0.0, 1.0, 0.0, 0.0).tolist()

            payload_alice = self._v1_payload("alice", semantic=[
                    self._with_provenance({
                        "rule": "cook 前先检查 update mode",
                        "category": "pitfall",
                        "abstraction_level": 2,
                        "confidence": 0.6,
                        "embedding": same_vec,
                        "embedding_backend": "fallback",
                    }),
                    self._with_provenance({
                        "rule": "不同的经验条目",
                        "category": "knowledge",
                        "abstraction_level": 3,
                        "confidence": 0.55,
                        "embedding": different_vec,
                        "embedding_backend": "fallback",
                    }),
                ])
            payload_bob = self._v1_payload("bob", semantic=[
                # 与 alice 的第一条语义近似重复（相同向量），但置信度更高，应保留 bob 这条内容
                    self._with_provenance({
                        "rule": "先检查 update mode 再 cook（更完整表述）",
                        "category": "pitfall",
                        "abstraction_level": 2,
                        "confidence": 0.9,
                        "embedding": same_vec,
                        "embedding_backend": "fallback",
                    }),
                    # 不合格：置信度不足，应被过滤
                    self._with_provenance({
                        "rule": "低质量条目",
                        "category": "debug",
                        "abstraction_level": 2,
                        "confidence": 0.1,
                        "embedding": different_vec,
                        "embedding_backend": "fallback",
                    }),
                ], procedural=[
                    self._with_provenance({
                        "strategy_name": "verify_before_modify",
                        "description": "改前先查现有结构",
                        "priority": 0.6,
                        "success_rate": 0.8,
                        "usage_count": 4,
                        "embedding": same_vec,
                        "embedding_backend": "fallback",
                    }),
                ])

            path_alice = self._write_export(temp_dir, "alice", payload_alice)
            path_bob = self._write_export(temp_dir, "bob", payload_bob)

            stats = rebuild_team_memory(
                db_path=Path(db_dir) / "team_memory.db",
                export_files=[("alice", path_alice), ("bob", path_bob)],
            )

            self.assertEqual(stats["scanned_users"], 2)
            self.assertEqual(stats["skipped_files"], 0)
            # 4 条输入中低质量条目先由统一资格策略过滤，3 条进入去重，最终剩 2 条。
            self.assertEqual(stats["semantic_raw"], 3)
            self.assertEqual(stats["semantic_merged"], 2)
            self.assertEqual(stats["procedural_merged"], 1)
            self.assertEqual(stats["ineligible_entries"], 1)

            store = TeamMemoryStore(db_path=Path(db_dir) / "team_memory.db")
            all_rules = {
                row[0]: json.loads(row[1])
                for row in store._get_conn().execute(
                    "SELECT rule, source_users FROM team_semantic_memory"
                ).fetchall()
            }
            # 保留的是置信度更高的 bob 版本内容，且 source_users 合并了 alice+bob
            self.assertIn("先检查 update mode 再 cook（更完整表述）", all_rules)
            self.assertEqual(sorted(all_rules["先检查 update mode 再 cook（更完整表述）"]), ["alice", "bob"])
            self.assertNotIn("低质量条目", all_rules)
            store.close()

    def test_search_semantic_and_procedural_round_trip(self):
        with TemporaryDirectory() as db_dir:
            store = TeamMemoryStore(db_path=Path(db_dir) / "team_memory.db")
            from houdini_agent.utils.team_memory_store import TeamSemanticRecord, TeamProceduralRecord
            from houdini_agent.utils.embedding import get_embedder

            embedder = get_embedder()
            try:
                store.replace_all(
                    semantic_records=[
                        TeamSemanticRecord(
                            rule="节点连接前先确认输入端口类型", category="pitfall",
                            abstraction_level=2, confidence=0.7,
                            embedding=embedder.encode("节点连接前先确认输入端口类型"),
                            source_users=["alice"],
                        ),
                    ],
                    procedural_records=[
                        TeamProceduralRecord(
                            strategy_name="verify_before_modify", description="改前先查",
                            priority=0.6, success_rate=0.8,
                            embedding=embedder.encode("verify_before_modify 改前先查"),
                            source_users=["bob"],
                        ),
                    ],
                )

                self.assertEqual(store.count_semantic(), 1)
                self.assertEqual(store.count_procedural(), 1)

                sem_results = store.search_semantic("随便什么查询", top_k=5)
                self.assertEqual(len(sem_results), 1)
                self.assertEqual(sem_results[0][0].source_users, ["alice"])

                proc_results = store.search_procedural("随便什么查询", top_k=5)
                self.assertEqual(len(proc_results), 1)
                self.assertEqual(proc_results[0][0].source_users, ["bob"])
            finally:
                store.close()

    def test_team_backend_model_and_dimension_mismatch_disable_scoring(self):
        with TemporaryDirectory() as db_dir:
            path = Path(db_dir) / "team_memory.db"
            original = FakeEmbedder("backend-a", "model-a", 4)
            store = TeamMemoryStore(path, original)
            from houdini_agent.utils.team_memory_store import TeamSemanticRecord
            store.replace_all([TeamSemanticRecord(rule="kept text", embedding=original.encode("kept text"))], [])
            store.close()

            for changed in (
                FakeEmbedder("backend-b", "model-a", 4),
                FakeEmbedder("backend-a", "model-b", 4),
                FakeEmbedder("backend-a", "model-a", 3),
            ):
                mismatched = TeamMemoryStore(path, changed)
                self.assertIsNotNone(mismatched.embedding_diagnostic)
                self.assertEqual(mismatched.search_semantic("query"), [])
                self.assertNotIn("query", changed.encoded_texts)
                mismatched.close()

    def test_rebuild_reembeds_final_text_and_replace_failure_preserves_live_db(self):
        with TemporaryDirectory() as export_dir, TemporaryDirectory() as db_dir:
            path = Path(db_dir) / "team_memory.db"
            path.write_bytes(b"old-live-db")
            payload = self._v1_payload("alice", semantic=[{
                    "rule": "final team text", "category": "knowledge", "abstraction_level": 2,
                    "confidence": 0.9, "embedding": _vec(1, 0, 0, 0).tolist(),
                    "embedding_backend": "old", "embedding_model": "old-model",
                    "embedding_dimension": 4, "embedding_format_version": 1,
                }])
            export_path = self._write_export(export_dir, "alice", payload)
            embedder = FakeEmbedder()
            with mock.patch("houdini_agent.utils.team_memory_store.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    rebuild_team_memory(embedder, path, [("alice", export_path)])
            self.assertEqual(path.read_bytes(), b"old-live-db")
            self.assertIn("final team text", embedder.encoded_texts)

    def test_rebuild_refreshes_default_singleton(self):
        import houdini_agent.utils.team_memory_store as module
        with TemporaryDirectory() as export_dir:
            payload = self._v1_payload("alice")
            export_path = self._write_export(export_dir, "alice", payload)
            old_path = module._TEAM_DB_PATH
            old_instance = module._team_store_instance
            try:
                module._TEAM_DB_PATH = Path(export_dir) / "live.db"
                module._team_store_instance = TeamMemoryStore(module._TEAM_DB_PATH, FakeEmbedder())
                previous = module._team_store_instance
                rebuild_team_memory(FakeEmbedder(), export_files=[("alice", export_path)])
                self.assertIsNot(module._team_store_instance, previous)
                self.assertEqual(module._team_store_instance.db_path, module._TEAM_DB_PATH)
            finally:
                if module._team_store_instance:
                    module._team_store_instance.close()
                module._team_store_instance = old_instance
                module._TEAM_DB_PATH = old_path

    def test_parser_keeps_valid_entries_and_reports_invalid_and_ineligible(self):
        with TemporaryDirectory() as export_dir:
            valid = self._with_provenance({
                "rule": "valid", "category": "knowledge", "abstraction_level": 2,
                "confidence": 0.9, "embedding": _vec(1, 0, 0, 0).tolist(),
                "embedding_backend": "fallback",
            })
            ineligible = dict(valid, rule="private", category="preference")
            payload = self._v1_payload("alice", semantic=[valid, "bad-entry", ineligible])
            path = self._write_export(export_dir, "alice", payload)
            result = parse_team_export_file(path, "alice")
            self.assertTrue(result.valid_document)
            self.assertEqual(len(result.semantic), 1)
            self.assertEqual(result.invalid_entries, 1)
            self.assertEqual(result.ineligible_entries, 1)
            self.assertEqual(result.diagnostics[0].reason, "semantic_not_object")
            self.assertNotIn("valid", result.diagnostics[0].to_dict())

    def test_parser_accepts_legacy_v0_but_rejects_unknown_version_and_username_mismatch(self):
        with TemporaryDirectory() as export_dir:
            legacy = {"semantic": [], "procedural": []}
            legacy_path = self._write_export(export_dir, "alice", legacy)
            self.assertTrue(parse_team_export_file(legacy_path, "alice").valid_document)

            unknown_path = self._write_export(
                export_dir, "unknown", {"schema_version": 99, "semantic": [], "procedural": []},
            )
            self.assertFalse(parse_team_export_file(unknown_path, "unknown").valid_document)

            mismatch_path = self._write_export(export_dir, "bob", self._v1_payload("alice"))
            mismatch = parse_team_export_file(mismatch_path, "bob")
            self.assertFalse(mismatch.valid_document)
            self.assertEqual(mismatch.diagnostics[0].reason, "username_mismatch")

    def test_parser_rejects_bad_embedding_and_oversized_file(self):
        with TemporaryDirectory() as export_dir:
            bad = self._with_provenance({
                "rule": "bad vector", "category": "knowledge", "abstraction_level": 2,
                "confidence": 0.9, "embedding": [1.0, float("nan")],
                "embedding_backend": "fallback",
            })
            path = self._write_export(export_dir, "alice", self._v1_payload("alice", semantic=[bad]))
            result = parse_team_export_file(path, "alice")
            self.assertTrue(result.valid_document)
            self.assertEqual(result.invalid_entries, 1)
            self.assertEqual(result.diagnostics[0].reason, "semantic_embedding_invalid")

            with mock.patch.object(Path, "stat") as stat:
                stat.return_value.st_size = MAX_EXPORT_FILE_BYTES + 1
                oversized = parse_team_export_file(path, "alice")
            self.assertFalse(oversized.valid_document)
            self.assertEqual(oversized.diagnostics[0].reason, "file_too_large")

    def test_rebuild_preserves_live_db_when_all_discovered_documents_are_invalid(self):
        with TemporaryDirectory() as export_dir, TemporaryDirectory() as db_dir:
            live_path = Path(db_dir) / "team_memory.db"
            live_path.write_bytes(b"existing")
            invalid_path = self._write_export(export_dir, "alice", ["not", "an", "object"])
            with self.assertRaises(RuntimeError):
                rebuild_team_memory(FakeEmbedder(), live_path, [("alice", invalid_path)])
            self.assertEqual(live_path.read_bytes(), b"existing")

    def test_rebuild_with_no_export_files_publishes_empty_database(self):
        with TemporaryDirectory() as db_dir:
            live_path = Path(db_dir) / "team_memory.db"
            stats = rebuild_team_memory(FakeEmbedder(), live_path, [])
            self.assertEqual(stats["scanned_users"], 0)
            store = TeamMemoryStore(live_path, FakeEmbedder())
            try:
                self.assertEqual(store.count_semantic(), 0)
                self.assertEqual(store.count_procedural(), 0)
            finally:
                store.close()


class PersonalMemoryProvenanceTest(unittest.TestCase):
    def test_legacy_database_disables_scoring_until_backed_up_migration(self):
        with TemporaryDirectory() as db_dir:
            path = Path(db_dir) / "personal.db"
            embedder = FakeEmbedder()
            store = MemoryStore(path, embedder)
            store.add_semantic(SemanticRecord(rule="text survives", confidence=0.9))
            store.close()
            conn = sqlite3.connect(str(path))
            try:
                conn.execute("DELETE FROM embedding_metadata")
                conn.commit()
            finally:
                conn.close()

            legacy = MemoryStore(path, embedder)
            self.assertIn("legacy", legacy.embedding_diagnostic)
            self.assertEqual(legacy.search_semantic("query"), [])
            self.assertNotIn("query", embedder.encoded_texts)
            backup = legacy.migrate_embeddings()
            self.assertTrue(backup.exists())
            self.assertIsNone(legacy.embedding_diagnostic)
            self.assertEqual(legacy.get_all_semantic()[0].rule, "text survives")
            legacy.close()


if __name__ == "__main__":
    unittest.main()
