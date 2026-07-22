# -*- coding: utf-8 -*-
"""Serializable cache record tests."""

import unittest

from houdini_agent.core.cache_records import DEFAULT_TOKEN_STATS, SessionCacheRecord, strip_images_for_cache


class CacheRecordsTest(unittest.TestCase):
    def test_strip_images_replaces_inline_base64_payloads(self):
        history = [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': 'look'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,abc123'}},
                {'type': 'image_url', 'image_url': {'url': 'https://example.test/image.png'}},
            ],
        }]

        stripped = strip_images_for_cache(history)

        self.assertEqual(stripped[0]['content'][1], {'type': 'text', 'text': '[Image: image/png]'})
        self.assertEqual(stripped[0]['content'][2], history[0]['content'][2])
        self.assertIsNot(stripped[0], history[0])
        self.assertIsNot(stripped[0]['content'][0], history[0]['content'][0])
        self.assertEqual(history[0]['content'][1]['image_url']['url'], 'data:image/png;base64,abc123')

    def test_session_cache_record_preserves_existing_cache_shape(self):
        record = SessionCacheRecord(
            session_id='abc12345',
            created_at='2026-07-22T15:00:00',
            conversation_history=[{'role': 'user', 'content': 'hello'}],
            context_summary='summary',
            todo_data=[{'text': 'todo'}],
            token_stats={'total_tokens': 12},
            estimated_tokens=34,
            todo_summary='1 todo',
        )

        cache_data = record.to_cache_data()

        self.assertEqual(cache_data['version'], '1.0')
        self.assertEqual(cache_data['session_id'], 'abc12345')
        self.assertEqual(cache_data['created_at'], '2026-07-22T15:00:00')
        self.assertEqual(cache_data['message_count'], 1)
        self.assertEqual(cache_data['conversation_history'], [{'role': 'user', 'content': 'hello'}])
        self.assertEqual(cache_data['context_summary'], 'summary')
        self.assertEqual(cache_data['todo_data'], [{'text': 'todo'}])
        self.assertEqual(cache_data['token_stats'], {'total_tokens': 12})
        self.assertEqual(cache_data['estimated_tokens'], 34)
        self.assertEqual(cache_data['todo_summary'], '1 todo')

    def test_from_cache_data_generates_missing_session_id_without_uuid_leak(self):
        record = SessionCacheRecord.from_cache_data({
            'conversation_history': [],
            'token_stats': DEFAULT_TOKEN_STATS.copy(),
        })

        self.assertEqual(len(record.session_id), 8)
        self.assertEqual(record.conversation_history, [])
        self.assertEqual(record.token_stats, DEFAULT_TOKEN_STATS)


if __name__ == "__main__":
    unittest.main()