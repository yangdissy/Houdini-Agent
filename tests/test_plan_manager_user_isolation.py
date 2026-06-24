# -*- coding: utf-8 -*-
"""PlanManager per-user storage isolation tests."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from houdini_agent.utils.plan_manager import get_plan_manager


class PlanManagerUserIsolationTest(unittest.TestCase):
    def test_same_session_id_is_isolated_by_user_cache_root(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_a_root = root / "cache" / "users" / "alice"
            user_b_root = root / "cache" / "users" / "bob"
            session_id = "shared-session"

            manager_a = get_plan_manager(user_a_root)
            manager_b = get_plan_manager(user_b_root)

            self.assertIs(manager_a, get_plan_manager(user_a_root))
            self.assertIsNot(manager_a, manager_b)

            manager_a.create_plan(session_id, {"title": "Alice Plan", "steps": [{"title": "A"}]})
            manager_b.create_plan(session_id, {"title": "Bob Plan", "steps": [{"title": "B"}]})

            self.assertEqual(manager_a.load_plan(session_id)["title"], "Alice Plan")
            self.assertEqual(manager_b.load_plan(session_id)["title"], "Bob Plan")
            self.assertTrue((user_a_root / "plans" / f"plan_{session_id}.json").exists())
            self.assertTrue((user_b_root / "plans" / f"plan_{session_id}.json").exists())
            self.assertFalse((root / "cache" / "plans" / f"plan_{session_id}.json").exists())


if __name__ == "__main__":
    unittest.main()
