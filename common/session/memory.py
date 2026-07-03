from __future__ import annotations

import gzip
import hashlib
import json
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Two-store memory manager for long-running pipeline sessions.

    Full-text storage
    -----------------
    Pages can be hundreds of KB. They are gzip-compressed and stored in
    Redis (if available) with a 24-hour TTL. In-process, only the N
    most-recently-accessed texts are kept (``lru_text_maxsize``).
    Others are evicted and re-fetched from Redis on demand.

    Summary storage
    ---------------
    Summaries are short (50–200 words). They are kept in an L1 LRU dict
    and replicated to Redis. Much cheaper than full text.

    Args:
        redis_backend:      Optional ``_RedisBackend`` from cache.py.
        lru_text_maxsize:   Max full-text entries to keep in process.
        lru_summary_maxsize: Max summaries to keep in process.
        full_text_ttl:      Redis TTL for full text (seconds, default 24h).
        summary_ttl:        Redis TTL for summaries (seconds, default 7 days).
    """

    DEFAULT_TEXT_TTL = 86_400  # 24h
    DEFAULT_SUMMARY_TTL = 7 * 86_400  # 7 days

    def __init__(
        self,
        redis_backend=None,
        lru_text_maxsize: int = 64,
        lru_summary_maxsize: int = 512,
        full_text_ttl: int = DEFAULT_TEXT_TTL,
        summary_ttl: int = DEFAULT_SUMMARY_TTL,
    ) -> None:
        self._redis = redis_backend
        self._text_ttl = full_text_ttl
        self._summary_ttl = summary_ttl
        self._lock = threading.Lock()

        self._text_lru: OrderedDict[str, bytes] = OrderedDict()
        self._text_max = lru_text_maxsize
        self._summary_lru: OrderedDict[str, str] = OrderedDict()
        self._summary_max = lru_summary_maxsize

    def store_full_text(self, session_id: str, url: str, text: str) -> None:
        """Store full page text compressed. Evicts old entries if over capacity."""
        key = _text_key(session_id, url)
        compressed = gzip.compress(text.encode("utf-8"), compresslevel=6)
        with self._lock:
            self._text_lru[key] = compressed
            self._text_lru.move_to_end(key)
            while len(self._text_lru) > self._text_max:
                evicted, _ = self._text_lru.popitem(last=False)
                logger.debug("MemoryManager: evicted full-text %s", evicted[:40])

        if self._redis and self._redis.available:
            self._redis.set(key, compressed, self._text_ttl)

    def get_full_text(self, session_id: str, url: str) -> str | None:
        """Return stored full text, or ``None`` if not found."""
        key = _text_key(session_id, url)
        with self._lock:
            if key in self._text_lru:
                self._text_lru.move_to_end(key)
                return gzip.decompress(self._text_lru[key]).decode("utf-8")

        # Try Redis
        if self._redis and self._redis.available:
            data = self._redis.get(key)
            if data:
                text = gzip.decompress(data).decode("utf-8")
                # Warm L1
                with self._lock:
                    self._text_lru[key] = data
                    self._text_lru.move_to_end(key)
                return text

        return None

    def evict_full_text(self, session_id: str, url: str) -> None:
        """Explicitly evict full text from in-process memory (keep on Redis)."""
        key = _text_key(session_id, url)
        with self._lock:
            self._text_lru.pop(key, None)

    def store_summary(self, session_id: str, url: str, summary: str) -> None:
        """Store an LLM-generated page/company summary."""
        key = _summary_key(session_id, url)
        with self._lock:
            self._summary_lru[key] = summary
            self._summary_lru.move_to_end(key)
            while len(self._summary_lru) > self._summary_max:
                self._summary_lru.popitem(last=False)

        if self._redis and self._redis.available:
            self._redis.set(
                key,
                gzip.compress(summary.encode(), compresslevel=6),
                self._summary_ttl,
            )

    def get_summary(self, session_id: str, url: str) -> str | None:
        """Return stored summary, or ``None``."""
        key = _summary_key(session_id, url)
        with self._lock:
            if key in self._summary_lru:
                self._summary_lru.move_to_end(key)
                return self._summary_lru[key]

        if self._redis and self._redis.available:
            data = self._redis.get(key)
            if data:
                summary = gzip.decompress(data).decode("utf-8")
                with self._lock:
                    self._summary_lru[key] = summary
                return summary

        return None

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "full_text_entries": len(self._text_lru),
                "full_text_max": self._text_max,
                "summary_entries": len(self._summary_lru),
                "summary_max": self._summary_max,
                "redis_available": bool(self._redis and self._redis.available),
            }

    @classmethod
    def from_config(cls, config) -> "MemoryManager":
        from common.session.cache import _RedisBackend

        redis = None
        if config.session.redis_enabled:
            redis = _RedisBackend(config.session.redis_url)
        return cls(
            redis_backend=redis,
            lru_text_maxsize=config.session.memory_lru_text_maxsize,
            lru_summary_maxsize=config.session.memory_lru_summary_maxsize,
        )


def _text_key(session_id: str, url: str) -> str:
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"mem:text:{session_id}:{url_hash}"


def _summary_key(session_id: str, url: str) -> str:
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"mem:summary:{session_id}:{url_hash}"
