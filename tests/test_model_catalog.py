# -*- coding: utf-8 -*-
"""Offline tests for provider model catalog refresh and fallback."""

import json
import tempfile
import threading
import unittest
from pathlib import Path

from houdini_agent.utils.model_catalog import (
    MODEL_CATALOG_TTL_SECONDS,
    PROVIDER_SOURCES,
    ModelCatalog,
)


class ModelCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temp_dir.name) / "catalog.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_enabled_provider_registry_preserves_static_models_and_endpoint_policy(self):
        self.assertEqual(set(PROVIDER_SOURCES), {
            "deepseek", "kimi_coding", "siliconflow", "of3d", "custom",
        })
        self.assertEqual(list(PROVIDER_SOURCES["deepseek"].static_models), [
            "deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner",
        ])
        self.assertEqual(list(PROVIDER_SOURCES["kimi_coding"].static_models), [
            "k3", "k3-256k", "kimi-for-coding", "kimi-for-coding-highspeed",
        ])
        self.assertEqual(list(PROVIDER_SOURCES["siliconflow"].static_models), [
            "deepseek-ai/DeepSeek-V4.1-Flash", "zai-org/GLM-5.3",
        ])
        self.assertEqual(list(PROVIDER_SOURCES["of3d"].static_models), [
            "gpt-5.6", "chatgpt-4o-latest",
        ])
        self.assertEqual(PROVIDER_SOURCES["deepseek"].models_url,
                         "https://api.deepseek.com/v1/models")
        for provider in ("kimi_coding", "siliconflow", "of3d", "custom"):
            self.assertIsNone(PROVIDER_SOURCES[provider].models_url)

    def test_refresh_filters_merges_and_caches_atomically(self):
        now = [1000.0]
        calls = []

        def transport(url, headers, timeout):
            calls.append((url, headers, timeout))
            return {"data": [
                {"id": "deepseek-chat"}, {"id": "new-model"},
                {"id": "new-model"}, {"id": ""}, {"id": 4},
                "invalid", {"id": "bad\nmodel"},
            ]}

        catalog = ModelCatalog(self.cache_path, transport, lambda: now[0])
        result = catalog.refresh_provider("deepseek", "secret")

        self.assertEqual(result, ["deepseek-chat", "new-model"])
        self.assertEqual(calls[0][0], "https://api.deepseek.com/v1/models")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer secret")
        self.assertEqual(catalog.models("deepseek"), result)
        self.assertEqual(json.loads(self.cache_path.read_text("utf-8"))["deepseek"]["models"], result)
        self.assertEqual(list(self.cache_path.parent.glob("*.tmp")), [])

    def test_ttl_expiry_and_failure_fall_back_without_clearing(self):
        now = [1000.0]
        catalog = ModelCatalog(
            self.cache_path,
            lambda *_: {"data": [{"id": "deepseek-chat"}]},
            lambda: now[0],
        )
        catalog.refresh_provider("deepseek", "key")
        self.assertEqual(catalog.models("deepseek"), ["deepseek-chat"])

        now[0] += MODEL_CATALOG_TTL_SECONDS
        self.assertEqual(catalog.models("deepseek"), catalog.static_models("deepseek"))
        failed = ModelCatalog(self.cache_path, lambda *_: (_ for _ in ()).throw(OSError("offline")), lambda: now[0])
        self.assertEqual(failed.refresh_provider("deepseek", "key"), failed.static_models("deepseek"))
        self.assertEqual(json.loads(self.cache_path.read_text("utf-8"))["deepseek"]["models"], ["deepseek-chat"])

    def test_missing_key_and_unconfirmed_endpoints_do_not_call_transport(self):
        def unexpected(*_):
            self.fail("transport must not be called")

        catalog = ModelCatalog(self.cache_path, unexpected)
        self.assertEqual(catalog.refresh_provider("deepseek"), catalog.static_models("deepseek"))
        for provider in ("kimi_coding", "siliconflow", "of3d", "custom"):
            self.assertEqual(catalog.refresh_provider(provider), catalog.static_models(provider))

    def test_concurrent_refresh_keeps_valid_json_cache(self):
        barrier = threading.Barrier(2)

        def transport(*_):
            barrier.wait(timeout=2)
            return {"data": [{"id": "deepseek-chat"}, {"id": "parallel"}]}

        catalog = ModelCatalog(self.cache_path, transport)
        threads = [threading.Thread(target=catalog.refresh_provider, args=("deepseek", "key"))
                   for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        data = json.loads(self.cache_path.read_text("utf-8"))
        self.assertEqual(data["deepseek"]["models"], ["deepseek-chat", "parallel"])


if __name__ == "__main__":
    unittest.main()
