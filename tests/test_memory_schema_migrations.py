import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from houdini_agent.utils.memory_store import MemoryStore
from tests.test_team_memory import FakeEmbedder


def create_legacy_database(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript("""
            CREATE TABLE episodic_memory (
                id TEXT PRIMARY KEY, timestamp REAL, session_id TEXT,
                task_description TEXT, actions TEXT, result_summary TEXT,
                success INTEGER, error_count INTEGER, retry_count INTEGER,
                reward_score REAL, embedding BLOB, importance REAL, tags TEXT
            );
            CREATE TABLE semantic_memory (
                id TEXT PRIMARY KEY, created_at REAL, updated_at REAL,
                rule TEXT, source_episodes TEXT, confidence REAL,
                activation_count INTEGER, embedding BLOB, category TEXT
            );
            CREATE TABLE procedural_memory (
                id TEXT PRIMARY KEY, strategy_name TEXT, description TEXT,
                priority REAL, success_rate REAL, usage_count INTEGER,
                last_used REAL, embedding BLOB, conditions TEXT
            );
            INSERT INTO semantic_memory VALUES (
                'semantic-1', 1.0, 1.0, 'legacy rule', '[]',
                0.7, 0, NULL, 'debug'
            );
        """)
        conn.commit()
    finally:
        conn.close()


class MemorySchemaMigrationTest(unittest.TestCase):
    def test_new_database_uses_latest_schema_version(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "agent_memory.db"
            store = MemoryStore(path, FakeEmbedder())
            store.close()

            conn = sqlite3.connect(str(path))
            try:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(semantic_memory)")
                }
            finally:
                conn.close()

            self.assertEqual(version, MemoryStore.SCHEMA_VERSION)
            self.assertIn("abstraction_level", columns)

    def test_legacy_database_is_upgraded_without_losing_data(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "agent_memory.db"
            create_legacy_database(path)

            store = MemoryStore(path, FakeEmbedder())
            try:
                saved = store.get_semantic("semantic-1")
                self.assertEqual(saved.rule, "legacy rule")
                self.assertEqual(saved.abstraction_level, 2)
            finally:
                store.close()

            conn = sqlite3.connect(str(path))
            try:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(version, MemoryStore.SCHEMA_VERSION)
            self.assertEqual(quick_check, "ok")

    def test_reopening_migrated_database_is_idempotent(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "agent_memory.db"
            create_legacy_database(path)

            first = MemoryStore(path, FakeEmbedder())
            first.close()
            second = MemoryStore(path, FakeEmbedder())
            try:
                self.assertEqual(second.count_semantic(), 1)
                self.assertEqual(second.get_semantic("semantic-1").abstraction_level, 2)
            finally:
                second.close()

    def test_failed_migration_rolls_back_schema_and_version(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "agent_memory.db"
            create_legacy_database(path)

            original = MemoryStore._migrate_v1_add_abstraction_level

            def fail_after_schema_change(conn):
                original(conn)
                raise sqlite3.DatabaseError("injected migration failure")

            with mock.patch.object(
                MemoryStore,
                "_migrate_v1_add_abstraction_level",
                side_effect=fail_after_schema_change,
            ):
                with self.assertRaisesRegex(sqlite3.DatabaseError, "injected"):
                    MemoryStore(path, FakeEmbedder())

            conn = sqlite3.connect(str(path))
            try:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(semantic_memory)")
                }
                quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(version, 0)
            self.assertNotIn("abstraction_level", columns)
            self.assertEqual(quick_check, "ok")


if __name__ == "__main__":
    unittest.main()