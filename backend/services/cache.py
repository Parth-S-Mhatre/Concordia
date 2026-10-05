"""Lightweight cache: in-memory TTL with optional Redis backing.

Spec §21 allows Redis or another caching mechanism. This module tries Redis
when REDIS_URL is configured and silently falls back to an in-memory store,
so repeated lookups (search results, suggestions, indexes) stay fast without
adding a hard infrastructure dependency for the demo.
"""

import json
import time
from typing import Any, Optional

from backend.config import settings

_memory: dict = {}


def _redis_client():
    url = getattr(settings, "redis_url", "")
    if not url:
        return None
    try:
        import redis  # type: ignore

        return redis.Redis.from_url(url, decode_responses=True, socket_timeout=2)
    except Exception:
        return None


_redis = None
_redis_tried = False


def _get_redis():
    global _redis, _redis_tried
    if not _redis_tried:
        _redis_tried = True
        _redis = _redis_client()
    return _redis


def cache_get(key: str) -> Optional[Any]:
    client = _get_redis()
    if client is not None:
        try:
            raw = client.get(f"cg:{key}")
            return json.loads(raw) if raw is not None else None
        except Exception:
            pass
    entry = _memory.get(key)
    if not entry:
        return None
    value, expires = entry
    if expires and expires < time.time():
        _memory.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> None:
    client = _get_redis()
    if client is not None:
        try:
            client.setex(f"cg:{key}", ttl_seconds, json.dumps(value, default=str))
        except Exception:
            pass
    _memory[key] = (value, time.time() + ttl_seconds if ttl_seconds else None)
    if len(_memory) > 2000:  # simple eviction guard
        oldest = next(iter(_memory))
        _memory.pop(oldest, None)


def cache_invalidate(prefix: str) -> None:
    client = _get_redis()
    if client is not None:
        try:
            for key in client.scan_iter(f"cg:{prefix}*"):
                client.delete(key)
        except Exception:
            pass
    for key in [k for k in _memory if k.startswith(prefix)]:
        _memory.pop(key, None)
