# -*- coding: utf-8 -*-
"""Provider model catalog with conservative, cached runtime refresh.

Only endpoints confirmed for an enabled provider are registered.  Providers
without a confirmed catalog endpoint keep their precompiled model list.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence
from urllib.request import Request, urlopen

MODEL_CATALOG_TTL_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class ProviderSource:
    provider_id: str
    display_name: str
    static_models: Sequence[str]
    models_url: Optional[str] = None
    requires_api_key: bool = False


PROVIDER_SOURCES: Dict[str, ProviderSource] = {
    "deepseek": ProviderSource(
        "deepseek", "DeepSeek",
        ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"),
        "https://api.deepseek.com/v1/models", True,
    ),
    "kimi_coding": ProviderSource(
        "kimi_coding", "Kimi Coding",
        ("k3", "k3-256k", "kimi-for-coding", "kimi-for-coding-highspeed"),
    ),
    "siliconflow": ProviderSource(
        "siliconflow", "SiliconFlow",
        ("deepseek-ai/DeepSeek-V4.1-Flash", "zai-org/GLM-5.3"),
    ),
    "of3d": ProviderSource(
        "of3d", "OF3D", ("gpt-5.6", "chatgpt-4o-latest"),
    ),
    "custom": ProviderSource("custom", "Custom", ()),
}

Transport = Callable[[str, Dict[str, str], float], object]
_CACHE_LOCK = threading.RLock()


def _default_transport(url: str, headers: Dict[str, str], timeout: float) -> object:
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _filter_model_ids(payload: object) -> List[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return []
    result = []
    seen = set()
    for item in payload["data"]:
        model_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(model_id, str):
            continue
        model_id = model_id.strip()
        if not model_id or len(model_id) > 256 or any(ord(ch) < 32 for ch in model_id):
            continue
        if model_id not in seen:
            seen.add(model_id)
            result.append(model_id)
    return result


def default_cache_path() -> Path:
    root = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(root) / "Houdini-Agent" / "model_catalog.json"


class ModelCatalog:
    """Resolve provider models with TTL cache and safe static fallback."""

    def __init__(
        self,
        cache_path: Optional[Path] = None,
        transport: Optional[Transport] = None,
        clock: Callable[[], float] = time.time,
        ttl_seconds: int = MODEL_CATALOG_TTL_SECONDS,
    ) -> None:
        self.cache_path = Path(cache_path) if cache_path else default_cache_path()
        self.transport = transport or _default_transport
        self.clock = clock
        self.ttl_seconds = ttl_seconds

    def static_models(self, provider_id: str) -> List[str]:
        source = PROVIDER_SOURCES.get(provider_id)
        return list(source.static_models) if source else []

    def models(self, provider_id: str, custom_models: Iterable[str] = ()) -> List[str]:
        if provider_id == "custom":
            return self._clean(custom_models)
        cached = self._cache_entry(provider_id, require_fresh=True)
        return list(cached["models"]) if cached else self.static_models(provider_id)

    def can_refresh(self, provider_id: str, api_key: str = "") -> bool:
        source = PROVIDER_SOURCES.get(provider_id)
        return bool(source and source.models_url and (api_key or not source.requires_api_key))

    def refresh_provider(self, provider_id: str, api_key: str = "") -> List[str]:
        source = PROVIDER_SOURCES.get(provider_id)
        fallback = self.models(provider_id)
        if not source or not source.models_url:
            return fallback
        if source.requires_api_key and not api_key:
            return fallback

        headers = {"Accept": "application/json", "User-Agent": "Houdini-Agent/model-catalog"}
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        try:
            payload = self.transport(source.models_url, headers, 10.0)
            live_models = _filter_model_ids(payload)
            if not live_models:
                return fallback
            models = self._merge(source.static_models, live_models)
            self._store_entry(provider_id, models)
            return models
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return fallback
        except Exception:
            # Provider/network failures must never clear a usable model list.
            return fallback

    @staticmethod
    def _clean(models: Iterable[str]) -> List[str]:
        result = []
        seen = set()
        for model in models:
            if isinstance(model, str):
                model = model.strip()
                if model and model not in seen:
                    seen.add(model)
                    result.append(model)
        return result

    @staticmethod
    def _merge(static_models: Sequence[str], live_models: Sequence[str]) -> List[str]:
        live = set(live_models)
        retained = [model for model in static_models if model in live]
        return retained + sorted(model for model in live_models if model not in retained)

    def _load_cache(self) -> dict:
        with _CACHE_LOCK:
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return {}

    def _cache_entry(self, provider_id: str, require_fresh: bool) -> Optional[dict]:
        entry = self._load_cache().get(provider_id)
        if not isinstance(entry, dict) or not self._clean(entry.get("models", [])):
            return None
        try:
            age = self.clock() - float(entry["updated_at"])
        except (KeyError, TypeError, ValueError):
            return None
        if require_fresh and (age < 0 or age >= self.ttl_seconds):
            return None
        return {"models": self._clean(entry["models"]), "updated_at": entry["updated_at"]}

    def _store_entry(self, provider_id: str, models: Sequence[str]) -> None:
        with _CACHE_LOCK:
            data = self._load_cache()
            data[provider_id] = {"models": list(models), "updated_at": self.clock()}
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=self.cache_path.name + ".", suffix=".tmp",
                dir=str(self.cache_path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(data, stream, ensure_ascii=False, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.cache_path)
            finally:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
