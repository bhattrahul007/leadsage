from __future__ import annotations

import gzip
import hashlib
import json
import logging
import threading
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

_APPROX_CHARS_PER_TOKEN = 4  # conservative estimate


def _count_tokens(text: str) -> int:
    """Approximate token count without tiktoken dependency."""
    return max(1, len(text) // _APPROX_CHARS_PER_TOKEN)


class LLMResponseCache:
    """
    Two-tier semantic cache for LLM structured responses.

    Key = SHA-256(model + "|" + prompt).
    L1 = in-process LRU dict (zero-latency).
    L2 = Redis with TTL (survives process restart).

    Usage::

        cache = LLMResponseCache(redis_backend, lru_maxsize=256)
        cached = cache.get(prompt, model_name)
        if cached is None:
            result = llm.invoke_structured(prompt, schema)
            cache.set(prompt, model_name, result, ttl=3600)
    """

    def __init__(
        self,
        redis_backend=None,
        lru_maxsize: int = 256,
    ) -> None:
        self._redis = redis_backend
        self._lru: OrderedDict[str, bytes] = OrderedDict()
        self._maxsize = lru_maxsize
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, prompt: str, model: str) -> Any | None:
        key = _cache_key(prompt, model)
        # L1
        with self._lock:
            if key in self._lru:
                self._lru.move_to_end(key)
                self._hits += 1
                return json.loads(gzip.decompress(self._lru[key]))
        # L2
        if self._redis and self._redis.available:
            raw = self._redis.get(key)
            if raw:
                self._hits += 1
                obj = json.loads(gzip.decompress(raw))
                with self._lock:
                    self._lru[key] = raw
                    self._lru.move_to_end(key)
                    self._evict()
                return obj
        self._misses += 1
        return None

    def set(self, prompt: str, model: str, value: Any, ttl: int = 3600) -> None:
        key = _cache_key(prompt, model)
        try:
            raw = gzip.compress(
                json.dumps(value, default=str, ensure_ascii=False).encode(), compresslevel=6
            )
        except Exception:
            return  # non-serializable, skip caching
        with self._lock:
            self._lru[key] = raw
            self._lru.move_to_end(key)
            self._evict()
        if self._redis and self._redis.available:
            self._redis.set(key, raw, ttl)

    def _evict(self) -> None:
        while len(self._lru) > self._maxsize:
            self._lru.popitem(last=False)

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._lru),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
        }


def _cache_key(prompt: str, model: str) -> str:
    h = hashlib.sha256(f"{model}|{prompt}".encode()).hexdigest()[:24]
    return f"llm_resp:{h}"
