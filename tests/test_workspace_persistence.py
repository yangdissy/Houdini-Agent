# -*- coding: utf-8 -*-
"""Pure workspace persistence tests (no Qt objects)."""

import json
import tempfile
import unittest
from pathlib import Path

from houdini_agent.core.session_state import SessionState
from houdini_agent.core.workspace_persistence import build_manifest, load_restore_plan, save_workspace


class WorkspacePersistenceTest(unittest.TestCase):
    def test_manifest_active_session_falls_back_to_first_saved(self):
        tabs = [{'session_id': 'one'}, {'session_id': 'two'}]
        self.assertEqual(build_manifest(tabs, 'missing')['active_session_id'], 'one')
        self.assertEqual(build_manifest(tabs, 'two')['active_session_id'], 'two')

    def test_empty_workspace_writes_manifest_and_clear_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = save_workspace(root, {'empty': SessionState('empty', 'now')},
                                   [('empty', 'Chat')], 'empty')
            self.assertFalse(saved)
            self.assertEqual(json.loads((root / 'sessions_manifest.json').read_text())['tabs'], [])
            self.assertTrue((root / 'sessions_cleared.json').exists())
            self.assertTrue(load_restore_plan(root).cleared)

    def test_second_staged_replace_failure_rolls_back_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_one = {'session_id': 'one', 'conversation_history': [{'content': 'old'}]}
            (root / 'session_one.json').write_text(json.dumps(old_one))
            old_manifest = {'version': '1.0', 'active_session_id': 'old', 'tabs': []}
            (root / 'sessions_manifest.json').write_text(json.dumps(old_manifest))
            states = {
                'one': SessionState('one', 'now', [{'content': 'new one'}]),
                'two': SessionState('two', 'now', [{'content': 'new two'}]),
            }

            def fail_second(source, target):
                if target.name == 'session_two.json':
                    raise PermissionError('occupied')
                source.replace(target)

            with self.assertRaises(PermissionError):
                save_workspace(root, states, [('one', 'One'), ('two', 'Two')], 'one', fail_second)
            self.assertEqual(json.loads((root / 'session_one.json').read_text()), old_one)
            self.assertEqual(json.loads((root / 'sessions_manifest.json').read_text()), old_manifest)

    def test_manifest_suppresses_orphan_but_missing_manifest_restores_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'session_orphan.json').write_text(json.dumps({
                'version': '1.0', 'session_id': 'orphan',
                'conversation_history': [{'role': 'user', 'content': 'orphan chat'}],
            }))
            (root / 'sessions_manifest.json').write_text(json.dumps({
                'version': '1.0', 'active_session_id': '', 'tabs': [],
            }))
            self.assertEqual(load_restore_plan(root).sessions, [])
            (root / 'sessions_manifest.json').unlink()
            plan = load_restore_plan(root)
            self.assertEqual(plan.sessions[0][0], 'orphan')
            self.assertEqual(plan.active_session_id, 'orphan')

    def test_session_state_keeps_cache_shape_and_legacy_widget_keys(self):
        widget = object()
        legacy = {'scroll_area': widget, 'conversation_history': [{'role': 'user', 'content': 'x'}]}
        state = SessionState.from_legacy_dict('sid', legacy)
        state.context_summary = 'summary'
        state.update_legacy_dict(legacy)
        self.assertIs(legacy['scroll_area'], widget)
        cache = state.to_cache_record().to_cache_data()
        self.assertEqual(cache['version'], '1.0')
        self.assertEqual(cache['message_count'], 1)
        self.assertNotIn('scroll_area', cache)


if __name__ == '__main__':
    unittest.main()