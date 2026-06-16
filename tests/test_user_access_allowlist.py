# -*- coding: utf-8 -*-
"""User allowlist access checks."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from shared.user_paths import is_user_allowed, load_user_allowlist


class UserAccessAllowlistTest(unittest.TestCase):
    def test_missing_allowlist_denies_access(self):
        with TemporaryDirectory() as temp_dir:
            access_path = Path(temp_dir) / ".access"

            self.assertFalse(is_user_allowed("yangdi", access_path))

    def test_plain_text_allowlist_supports_comments_and_normalization(self):
        with TemporaryDirectory() as temp_dir:
            access_path = Path(temp_dir) / ".access"
            access_path.write_text("# local access\nYangDi\n team_01  # enabled\n", encoding="utf-8")

            self.assertEqual(load_user_allowlist(access_path), {"yangdi", "team_01"})
            self.assertTrue(is_user_allowed(" YANGDI ", access_path))
            self.assertTrue(is_user_allowed("team_01", access_path))
            self.assertFalse(is_user_allowed("new_user", access_path))

    def test_json_list_allowlist(self):
        with TemporaryDirectory() as temp_dir:
            access_path = Path(temp_dir) / ".access"
            access_path.write_text('["YangDi", "recce", 123]', encoding="utf-8")

            self.assertEqual(load_user_allowlist(access_path), {"yangdi", "recce"})

    def test_json_object_allowlist(self):
        with TemporaryDirectory() as temp_dir:
            access_path = Path(temp_dir) / ".access"
            access_path.write_text('{"users": ["FanjinJun", "bad-name!"]}', encoding="utf-8")

            self.assertEqual(load_user_allowlist(access_path), {"fanjinjun"})


if __name__ == "__main__":
    unittest.main()