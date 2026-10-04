from __future__ import annotations

import copy
import hashlib
import time
from dataclasses import dataclass

import httpx

from .providers import ProviderConfig, build_provider, normalize_base_url

MODEL_CACHE_TTL_SECONDS = 600.0


@dataclass(frozen=True)
class ModelCacheEntry:
    models: tuple[str, ...]
    metadata_by_id: dict[str, dict]
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
        return f"{identity_id}:{config.provider_kind}:{base_url}:{fingerprint}"

    def peek_metadata(self, identity_id: str, config: ProviderConfig) -> dict[str, dict]:
        """Read unexpired public discovery facts without issuing any request."""
        cached = self._cache.get(self._cache_key(identity_id, config))
        if cached is None or cached.expires_at <= time.monotonic():
            return {}
        return copy.deepcopy(cached.metadata_by_id)

    async def discover(
        self,
        identity_id: str,
        config: ProviderConfig,
        *,
        force_refresh: bool = False,
    ) -> tuple[list[str], bool]:
        models, _metadata, cached = await self.discover_details(identity_id, config, force_refresh=force_refresh)
        return models, cached

    async def discover_details(
        self,
        identity_id: str,
        config: ProviderConfig,
        *,
        force_refresh: bool = False,
    ) -> tuple[list[str], dict[str, dict], bool]:
        key = self._cache_key(identity_id, config)
        now = time.monotonic()
        cached = self._cache.get(key)
        if not force_refresh and cached and cached.expires_at > now:
            return list(cached.models), copy.deepcopy(cached.metadata_by_id), True
        provider = build_provider(config, transport=self.transport)
        catalog = await provider.list_model_catalog()
        models = [entry['id'] for entry in catalog]
        metadata = {entry['id']: entry['reasoning_metadata'] for entry in catalog if 'reasoning_metadata' in entry}
        self._cache[key] = ModelCacheEntry(
            models=tuple(models),
            metadata_by_id=copy.deepcopy(metadata),
            expires_at=now + MODEL_CACHE_TTL_SECONDS,
        )
        return models, metadata, False
