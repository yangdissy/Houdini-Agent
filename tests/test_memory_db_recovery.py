import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from houdini_agent.utils.memory_sqlite import (
    copy_legacy_non_sqlite,
    dismiss_memory_db_conflict,
    is_sqlite_artifact,
    overwrite_authoritative_with_leftover,
    restore_legacy_local_memory_db,
)
from houdini_agent.utils.memory_store import MemoryStore, SemanticRecord
from shared.user_paths import UserPaths
from tests.test_team_memory import FakeEmbedder


class MemoryDbRecoveryTest(unittest.TestCase):
    def test_restores_leftover_local_database_into_user_directory(self):
        with TemporaryDirectory() as repo_root, TemporaryDirectory() as local_app_data:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root), mock.patch.dict(
                "os.environ", {"LOCALAPPDATA": local_app_data}
            ):
                paths = UserPaths("recovery_tester")
                leftover = paths.legacy_local_memory_db()
                leftover.parent.mkdir(parents=True, exist_ok=True)
                leftover_store = MemoryStore(db_path=leftover, embedder=FakeEmbedder())
                leftover_store.add_semantic(SemanticRecord(rule="恢复这条记忆", category="preference"))
                leftover_store.close()

                result = restore_legacy_local_memory_db(paths)

                self.assertEqual(result.status, "restored")
                restored = MemoryStore(db_path=paths.memory_db(), embedder=FakeEmbedder())
                try:
                    rules = [rec.rule for rec in restored.get_all_semantic()]
                    self.assertIn("恢复这条记忆", rules)
                finally:
                    restored.close()
                self.assertTrue(leftover.exists())

    def test_does_not_overwrite_conflicting_authoritative_database(self):
        with TemporaryDirectory() as repo_root, TemporaryDirectory() as local_app_data:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root), mock.patch.dict(
                "os.environ", {"LOCALAPPDATA": local_app_data}
            ):
                paths = UserPaths("recovery_tester")
                leftover = paths.legacy_local_memory_db()
                leftover.parent.mkdir(parents=True, exist_ok=True)
                leftover_store = MemoryStore(db_path=leftover, embedder=FakeEmbedder())
                leftover_store.add_semantic(SemanticRecord(rule="本地残留记忆", category="preference"))
                leftover_store.close()

                auth_store = MemoryStore(db_path=paths.memory_db(), embedder=FakeEmbedder())
                auth_store.add_semantic(SemanticRecord(rule="U盘权威记忆", category="preference"))
                auth_store.close()

                result = restore_legacy_local_memory_db(paths)

                self.assertEqual(result.status, "conflict")
                auth_store = MemoryStore(db_path=paths.memory_db(), embedder=FakeEmbedder())
                try:
                    rules = [rec.rule for rec in auth_store.get_all_semantic()]
                    self.assertIn("U盘权威记忆", rules)
                    self.assertNotIn("本地残留记忆", rules)
                finally:
                    auth_store.close()

    def test_overwrite_authoritative_with_leftover_backs_up_and_replaces(self):
        with TemporaryDirectory() as repo_root, TemporaryDirectory() as local_app_data:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root), mock.patch.dict(
                "os.environ", {"LOCALAPPDATA": local_app_data}
            ):
                paths = UserPaths("recovery_tester")
                leftover = paths.legacy_local_memory_db()
                leftover.parent.mkdir(parents=True, exist_ok=True)
                leftover_store = MemoryStore(db_path=leftover, embedder=FakeEmbedder())
                leftover_store.add_semantic(SemanticRecord(rule="本地残留记忆", category="preference"))
                leftover_store.close()

                auth_store = MemoryStore(db_path=paths.memory_db(), embedder=FakeEmbedder())
                auth_store.add_semantic(SemanticRecord(rule="U盘权威记忆", category="preference"))
                auth_store.close()

                result = overwrite_authoritative_with_leftover(paths)

                self.assertEqual(result.status, "restored")
                # 权威库已被残留库内容替换
                auth_store = MemoryStore(db_path=paths.memory_db(), embedder=FakeEmbedder())
                try:
                    rules = [rec.rule for rec in auth_store.get_all_semantic()]
                    self.assertIn("本地残留记忆", rules)
                    self.assertNotIn("U盘权威记忆", rules)
                finally:
                    auth_store.close()
                # 旧权威库已备份
                backup = paths.memory_db().with_name("agent_memory.db.pre-overwrite-backup")
                self.assertTrue(backup.exists())
                # 已写恢复标记，且本地残留库已被删除，下次启动不再弹冲突
                result2 = restore_legacy_local_memory_db(paths)
                self.assertEqual(result2.status, "skipped")
                self.assertFalse(leftover.exists())

    def test_dismiss_conflict_keeps_authoritative_and_deletes_leftover(self):
        with TemporaryDirectory() as repo_root, TemporaryDirectory() as local_app_data:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root), mock.patch.dict(
                "os.environ", {"LOCALAPPDATA": local_app_data}
            ):
                paths = UserPaths("recovery_tester")
                leftover = paths.legacy_local_memory_db()
                leftover.parent.mkdir(parents=True, exist_ok=True)
                leftover_store = MemoryStore(db_path=leftover, embedder=FakeEmbedder())
                leftover_store.add_semantic(SemanticRecord(rule="本地残留记忆", category="preference"))
                leftover_store.close()
                auth_store = MemoryStore(db_path=paths.memory_db(), embedder=FakeEmbedder())
                auth_store.add_semantic(SemanticRecord(rule="U盘权威记忆", category="preference"))
                auth_store.close()

                self.assertEqual(restore_legacy_local_memory_db(paths).status, "conflict")
                result = dismiss_memory_db_conflict(paths)
                self.assertEqual(result.status, "skipped")
                # 本地残留库被删除，权威库内容不变
                self.assertFalse(leftover.exists())
                auth_store = MemoryStore(db_path=paths.memory_db(), embedder=FakeEmbedder())
                try:
                    rules = [rec.rule for rec in auth_store.get_all_semantic()]
                    self.assertIn("U盘权威记忆", rules)
                    self.assertNotIn("本地残留记忆", rules)
                finally:
                    auth_store.close()
                # 下次启动跳过
                self.assertEqual(restore_legacy_local_memory_db(paths).status, "skipped")

    def test_legacy_file_copy_skips_sqlite_artifacts(self):
        with TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "src"
            dst = Path(temp_dir) / "dst"
            src.mkdir()
            (src / "notes.txt").write_text("keep", encoding="utf-8")
            (src / "agent_memory.db").write_bytes(b"db")
            (src / "agent_memory.db-wal").write_bytes(b"wal")
            (src / "agent_memory.db-shm").write_bytes(b"shm")

            copy_legacy_non_sqlite(src, dst)

            self.assertTrue((dst / "notes.txt").exists())
            self.assertFalse((dst / "agent_memory.db").exists())
            self.assertFalse((dst / "agent_memory.db-wal").exists())
            self.assertFalse((dst / "agent_memory.db-shm").exists())
            self.assertTrue(is_sqlite_artifact(src / "agent_memory.db"))



if __name__ == "__main__":
    unittest.main()
