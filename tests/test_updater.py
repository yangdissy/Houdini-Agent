import json
import sys
from types import SimpleNamespace

import pytest

from houdini_agent.utils import updater


@pytest.mark.parametrize("repo_value", [None, "Kazama-Suichiku/Houdini-Agent"])
def test_foreign_or_legacy_cache_is_ignored_on_network_error(tmp_path, monkeypatch, repo_value):
    cache = {
        "etag": "old",
        "release_data": {
            "tag_name": "v99.0.0",
            "zipball_url": "https://example.invalid/upstream.zip",
        },
    }
    if repo_value is not None:
        cache["repo"] = repo_value
    cache_file = tmp_path / "update_cache.json"
    cache_file.write_text(json.dumps(cache), encoding="utf-8")
    requested_urls = []

    def fail_get(url, **kwargs):
        requested_urls.append(url)
        raise RuntimeError("offline")

    monkeypatch.setattr(updater, "_ETAG_CACHE_FILE", cache_file)
    monkeypatch.setattr(updater, "_cached_zipball_url", "")
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=fail_get))

    result = updater.check_update()

    assert requested_urls == ["https://api.github.com/repos/yangdissy/Houdini-Agent/releases/latest"]
    assert result["has_update"] is False
    assert updater._cached_zipball_url == ""