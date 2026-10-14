import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from shared.user_paths import UserPaths


class UserMemoryPathTest(unittest.TestCase):
    def test_capture_session_directory_rejects_path_like_session_ids(self):
        with TemporaryDirectory() as repo_root:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root):
                paths = UserPaths("Path_Tester")

                self.assertEqual(
                    paths.capture_session_dir("session-01"),
                    Path(repo_root) / "cache" / "users" / "path_tester" / "workspace" / "captures" / "session-01",
                )
                for invalid in ("", "../escape", "a/b", "a\\b", "session id"):
                    with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                        paths.capture_session_dir(invalid)

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

    def test_ensure_dirs_creates_default_user_skill_directory_and_config(self):
        with TemporaryDirectory() as repo_root:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root):
                paths = UserPaths("Path_Tester")
                paths.ensure_dirs()

                expected = Path(repo_root) / "cache" / "users" / "path_tester" / "skills"
                self.assertTrue(expected.is_dir())
                self.assertEqual(paths.configured_skills_dir(), expected)
                config_text = paths.user_config_path().read_text(encoding="utf-8")
                self.assertIn("[skills]", config_text)
                self.assertIn(f"user_skill_dir = {expected}", config_text)

    def test_ensure_dirs_preserves_legacy_flat_user_config(self):
        with TemporaryDirectory() as repo_root:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root):
                paths = UserPaths("Path_Tester")
                paths.user_root.mkdir(parents=True)
                paths.user_config_path().write_text(
                    "custom_models:kimi-k2.6\ndeepseek_api_key:secret\n", encoding="utf-8"
                )

                paths.ensure_dirs()

                config_text = paths.user_config_path().read_text(encoding="utf-8")
                self.assertIn("custom_models:kimi-k2.6", config_text)
                self.assertIn("deepseek_api_key:secret", config_text)
                self.assertEqual(config_text.count("[skills]"), 1)

    def test_users_have_isolated_skill_directories(self):
        with TemporaryDirectory() as repo_root:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root):
                first = UserPaths("User_One")
                second = UserPaths("User_Two")
                first.ensure_dirs()
                second.ensure_dirs()

                self.assertNotEqual(first.configured_skills_dir(), second.configured_skills_dir())
                self.assertEqual(first.configured_skills_dir(), first.skills_dir())
                self.assertEqual(second.configured_skills_dir(), second.skills_dir())

    def test_set_skills_dir_updates_existing_section_without_duplication(self):
        with TemporaryDirectory() as repo_root, TemporaryDirectory() as custom_dir:
            with mock.patch("shared.user_paths.get_repo_root", return_value=repo_root):
                paths = UserPaths("Path_Tester")
                paths.ensure_dirs()

                paths.set_skills_dir(Path(custom_dir))

                config_text = paths.user_config_path().read_text(encoding="utf-8")
                self.assertEqual(config_text.count("[skills]"), 1)
                self.assertEqual(paths.configured_skills_dir(), Path(custom_dir).resolve())


if __name__ == "__main__":
    unittest.main()
