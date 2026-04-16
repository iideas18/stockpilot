"""Data caching layer — supports Redis and SQLite backends."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class CacheBackend:
    """Abstract cache interface."""

    def get(self, key: str) -> str | None:
        raise NotImplementedError

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


class MemoryCache(CacheBackend):
    """Simple in-memory cache (for development)."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    def get(self, key: str) -> str | None:
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if expires_at and time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        expires_at = (time.time() + ttl) if ttl else None
        self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


class RedisCache(CacheBackend):
    """Redis-backed cache."""

    def __init__(self, url: str = "redis://localhost:6379/0") -> None:
        try:
            import redis
            self._client = redis.from_url(url, decode_responses=True)
            self._client.ping()
            logger.info("Redis cache connected: %s", url)
        except Exception as e:
            logger.warning("Redis unavailable (%s), falling back to memory cache", e)
            self._client = None
            self._fallback = MemoryCache()

    def get(self, key: str) -> str | None:
        if self._client is None:
            return self._fallback.get(key)
        return self._client.get(f"stockpilot:{key}")

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        if self._client is None:
            return self._fallback.set(key, value, ttl)
        self._client.set(f"stockpilot:{key}", value, ex=ttl)

    def delete(self, key: str) -> None:
        if self._client is None:
            return self._fallback.delete(key)
        self._client.delete(f"stockpilot:{key}")

    def clear(self) -> None:
        if self._client is None:
            return self._fallback.clear()
        for key in self._client.scan_iter("stockpilot:*"):
            self._client.delete(key)


class DataCache:
    """High-level cache for DataFrames and dicts with automatic serialization."""

    def __init__(self, backend: CacheBackend, default_ttl: int = 3600) -> None:
        self._backend = backend
        self._default_ttl = default_ttl

    @staticmethod
    def make_key(prefix: str, **kwargs: Any) -> str:
        """Generate a deterministic cache key."""
        raw = f"{prefix}:" + json.dumps(kwargs, sort_keys=True, default=str)
        return hashlib.md5(raw.encode()).hexdigest()

    def get_dataframe(self, key: str) -> pd.DataFrame | None:
        data = self._backend.get(key)
        if data is None:
            return None
        try:
            return pd.read_json(data, orient="records")
        except Exception:
            return None

    def set_dataframe(self, key: str, df: pd.DataFrame, ttl: int | None = None) -> None:
        try:
            data = df.to_json(orient="records", date_format="iso")
            self._backend.set(key, data, ttl or self._default_ttl)
        except Exception as e:
            logger.warning("Cache set failed for %s: %s", key, e)

    def get_dict(self, key: str) -> dict | None:
        data = self._backend.get(key)
        if data is None:
            return None
        try:
            return json.loads(data)
        except Exception:
            return None

    def set_dict(self, key: str, value: dict, ttl: int | None = None) -> None:
        try:
            self._backend.set(key, json.dumps(value, default=str), ttl or self._default_ttl)
        except Exception as e:
            logger.warning("Cache set failed for %s: %s", key, e)
