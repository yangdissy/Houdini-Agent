import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from shared.user_paths import UserPaths


class UserMemoryPathTest(unittest.TestCase):
    def test_memory_database_is_inside_user_memory_directory(self):
        with TemporaryDirectory() as repo_root:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root):
                paths = UserPaths("Path_Tester")

                self.assertEqual(
                    paths.memory_db(),
                    Path(repo_root) / "cache" / "users" / "path_tester" / "memory" / "agent_memory.db",
                )

    def test_legacy_local_database_is_only_a_recovery_source(self):
        with TemporaryDirectory() as repo_root, TemporaryDirectory() as local_app_data:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root), mock.patch.dict(
                "os.environ", {"LOCALAPPDATA": local_app_data}
            ):
                paths = UserPaths("Path_Tester")

                self.assertEqual(
                    paths.legacy_local_memory_db(),
                    Path(local_app_data) / "HoudiniAgent" / "memory" / "path_tester" / "agent_memory.db",
                )
                self.assertNotEqual(paths.memory_db(), paths.legacy_local_memory_db())


if __name__ == "__main__":
    unittest.main()
