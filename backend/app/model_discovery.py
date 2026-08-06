from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import httpx

from .providers import ProviderConfig, build_provider, normalize_base_url

MODEL_CACHE_TTL_SECONDS = 600.0


@dataclass(frozen=True)
class ModelCacheEntry:
    models: tuple[str, ...]
    expires_at: float


class ModelDiscoveryService:
    """进程内模型缓存；缓存键不包含可逆 API key。"""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport
        self._cache: dict[str, ModelCacheEntry] = {}

    @staticmethod
    def _cache_key(identity_id: str, config: ProviderConfig) -> str:
        base_url = normalize_base_url(config.base_url)
        fingerprint = hashlib.sha256(config.api_key.encode("utf-8")).hexdigest()
        return f"{identity_id}:{base_url}:{fingerprint}"

    async def discover(
        self,
        identity_id: str,
        config: ProviderConfig,
        *,
        force_refresh: bool = False,
    ) -> tuple[list[str], bool]:
        key = self._cache_key(identity_id, config)
        now = time.monotonic()
        cached = self._cache.get(key)
        if not force_refresh and cached and cached.expires_at > now:
            return list(cached.models), True
        provider = build_provider(config, transport=self.transport)
        models = await provider.list_models()
        self._cache[key] = ModelCacheEntry(
            models=tuple(models),
            expires_at=now + MODEL_CACHE_TTL_SECONDS,
        )
        return models, False
