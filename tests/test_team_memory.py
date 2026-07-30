# -*- coding: utf-8 -*-
"""Team memory sharing: export eligibility, opt-out toggle, and rebuild/dedup tests."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from houdini_agent.utils.memory_store import MemoryStore, SemanticRecord, ProceduralRecord
from houdini_agent.utils.team_memory_export import (
    build_team_export_payload,
    export_team_memory,
)
from houdini_agent.utils.team_memory_settings import (
    is_team_export_enabled,
    set_team_export_enabled,
)
from houdini_agent.utils.team_memory_store import TeamMemoryStore, rebuild_team_memory


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

    def test_rebuild_dedupes_similar_entries_and_unions_contributors(self):
        with TemporaryDirectory() as temp_dir, TemporaryDirectory() as db_dir:
            same_vec = _vec(1.0, 0.0, 0.0, 0.0).tolist()
            different_vec = _vec(0.0, 1.0, 0.0, 0.0).tolist()

            payload_alice = {
                "semantic": [
                    {
                        "rule": "cook 前先检查 update mode",
                        "category": "pitfall",
                        "abstraction_level": 2,
                        "confidence": 0.6,
                        "embedding": same_vec,
                        "embedding_backend": "fallback",
                    },
                    {
                        "rule": "不同的经验条目",
                        "category": "knowledge",
                        "abstraction_level": 3,
                        "confidence": 0.55,
                        "embedding": different_vec,
                        "embedding_backend": "fallback",
                    },
                ],
                "procedural": [],
            }
            payload_bob = {
                # 与 alice 的第一条语义近似重复（相同向量），但置信度更高，应保留 bob 这条内容
                "semantic": [
                    {
                        "rule": "先检查 update mode 再 cook（更完整表述）",
                        "category": "pitfall",
                        "abstraction_level": 2,
                        "confidence": 0.9,
                        "embedding": same_vec,
                        "embedding_backend": "fallback",
                    },
                    # 不合格：置信度不足，应被过滤
                    {
                        "rule": "低质量条目",
                        "category": "debug",
                        "abstraction_level": 2,
                        "confidence": 0.1,
                        "embedding": different_vec,
                        "embedding_backend": "fallback",
                    },
                ],
                "procedural": [
                    {
                        "strategy_name": "verify_before_modify",
                        "description": "改前先查现有结构",
                        "priority": 0.6,
                        "success_rate": 0.8,
                        "usage_count": 4,
                        "embedding": same_vec,
                        "embedding_backend": "fallback",
                    },
                ],
            }

            path_alice = self._write_export(temp_dir, "alice", payload_alice)
            path_bob = self._write_export(temp_dir, "bob", payload_bob)

            stats = rebuild_team_memory(
                db_path=Path(db_dir) / "team_memory.db",
                export_files=[("alice", path_alice), ("bob", path_bob)],
            )

            self.assertEqual(stats["scanned_users"], 2)
            self.assertEqual(stats["skipped_files"], 0)
            # alice 2 + bob 2 = 4 条原始语义，去重后应剩 2 条（重复的 pitfall 合并，低质量的被过滤）
            self.assertEqual(stats["semantic_raw"], 4)
            self.assertEqual(stats["semantic_merged"], 2)
            self.assertEqual(stats["procedural_merged"], 1)

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


if __name__ == "__main__":
    unittest.main()
