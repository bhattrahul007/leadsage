from __future__ import annotations

from collections import OrderedDict
import gzip
import hashlib
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)


class _LRUCache:
    """Thread-safe LRU dict with TTL support."""

    def __init__(self, maxsize: int = 512) -> None:
        self._cache: OrderedDict[str, tuple[bytes, float]] = OrderedDict()
        self._maxsize = maxsize
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> bytes | None:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            value, expires_at = self._cache[key]
            if expires_at != 0 and time.monotonic() > expires_at:
                del self._cache[key]
                self._misses += 1
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: bytes, ttl: int = 0) -> None:
        with self._lock:
            expires_at = (time.monotonic() + ttl) if ttl > 0 else 0
            self._cache[key] = (value, expires_at)
            self._cache.move_to_end(key)
            # Evict LRU entries if over capacity
            while len(self._cache) > self._maxsize:
                evicted_key, _ = self._cache.popitem(last=False)
                logger.debug("LRU evicted: %s", evicted_key)

    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    @property
    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total else 0.0,
            }


# ---------------------------------------------------------------------------
# Redis wrapper (optional)
# ---------------------------------------------------------------------------


class _RedisBackend:
    """Thin wrapper around redis-py with connection pool. Returns None on any error."""

    def __init__(
        self,
        url: str,
        pool_size: int = 20,
        socket_timeout: int = 5,
        retry_on_timeout: bool = True,
    ) -> None:
        try:
            import redis
            from redis.backoff import ExponentialBackoff
            from redis.retry import Retry

            retry = (
                Retry(ExponentialBackoff(cap=0.5, base=0.1), retries=3)
                if retry_on_timeout
                else None
            )
            pool = redis.ConnectionPool.from_url(
                url,
                max_connections=pool_size,
                decode_responses=False,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_timeout,
                retry=retry,
                retry_on_timeout=retry_on_timeout,
            )
            self._r = redis.Redis(connection_pool=pool)
            self._r.ping()
            self._available = True
            logger.info("Redis cache connected (pool_size=%d): %s", pool_size, url)
        except Exception as exc:
            self._r = None
            self._available = False
            logger.warning("Redis unavailable (%s) — using in-memory cache only", exc)

    @property
    def available(self) -> bool:
        return self._available

    def get(self, key: str) -> bytes | None:
        try:
            return self._r.get(key)
        except Exception as exc:
            logger.debug("Redis get error: %s", exc)
            return None

    def set(self, key: str, value: bytes, ttl: int = 0) -> None:
        try:
            if ttl > 0:
                self._r.setex(key, ttl, value)
            else:
                self._r.set(key, value)
        except Exception as exc:
            logger.debug("Redis set error: %s", exc)

    def delete(self, key: str) -> None:
        try:
            self._r.delete(key)
        except Exception:
            pass

    def get_dict(self, key: str) -> dict | None:
        try:
            return self._r.hgetall(key) or None
        except Exception:
            return None

    def set_dict(self, key: str, data: dict, ttl: int = 0) -> None:
        try:
            self._r.hset(key, mapping={k: v for k, v in data.items()})
            if ttl > 0:
                self._r.expire(key, ttl)
        except Exception as exc:
            logger.debug("Redis hset error: %s", exc)


# ---------------------------------------------------------------------------
# Lead Cache
# ---------------------------------------------------------------------------


class LeadCache:
    """
    Two-tier (Redis L2 + LRU L1) cache for pipeline objects.

    What is cached
    --------------
    ``CrawledPage``   — by URL SHA-256. Avoids re-crawling recently seen pages.
    ``ScoredLead``    — by domain. Avoids re-scoring the same company.
    ``session:state`` — session state dict (managed by SessionManager).

    Both tiers are checked on reads (L1 first). Writes go to both.
    """

    # TTL defaults (seconds)
    DEFAULT_CRAWL_TTL = 86_400  # 24h
    DEFAULT_LEAD_TTL = 7 * 86_400  # 7 days

    def __init__(
        self,
        redis_url: str | None = None,
        lru_maxsize: int = 512,
        crawl_ttl: int = DEFAULT_CRAWL_TTL,
        lead_ttl: int = DEFAULT_LEAD_TTL,
    ) -> None:
        self._lru = _LRUCache(maxsize=lru_maxsize)
        self._redis = _RedisBackend(redis_url) if redis_url else None
        self._crawl_ttl = crawl_ttl
        self._lead_ttl = lead_ttl

    # ------------------------------------------------------------------
    # CrawledPage
    # ------------------------------------------------------------------

    def get_crawled_page(self, url: str):
        """Return a cached ``CrawledPage`` or ``None``."""

        key = _crawl_key(url)
        data = self._get(key)
        if data is None:
            return None
        try:
            return _deserialize_page(data)
        except Exception as exc:
            logger.debug("Failed to deserialize cached page for %s: %s", url, exc)
            return None

    def set_crawled_page(self, url: str, page, ttl: int | None = None) -> None:
        """Cache a ``CrawledPage``."""
        key = _crawl_key(url)
        try:
            data = _serialize_page(page)
            self._set(key, data, ttl or self._crawl_ttl)
        except Exception as exc:
            logger.debug("Failed to serialize page for %s: %s", url, exc)

    # ------------------------------------------------------------------
    # ScoredLead
    # ------------------------------------------------------------------

    def get_lead(self, domain: str):
        """Return a cached ``ScoredLead`` or ``None``."""
        key = _lead_key(domain)
        data = self._get(key)
        if data is None:
            return None
        try:
            from common.schemas.lead_output import ScoredLead

            return ScoredLead.model_validate_json(_decompress(data))
        except Exception as exc:
            logger.debug("Failed to deserialize cached lead for %s: %s", domain, exc)
            return None

    def set_lead(self, domain: str, lead, ttl: int | None = None) -> None:
        """Cache a ``ScoredLead``."""
        key = _lead_key(domain)
        try:
            data = _compress(lead.model_dump_json())
            self._set(key, data, ttl or self._lead_ttl)
        except Exception as exc:
            logger.debug("Failed to cache lead for %s: %s", domain, exc)

    # ------------------------------------------------------------------
    # Session state (raw dict)
    # ------------------------------------------------------------------

    def get_session_state(self, session_id: str) -> dict | None:
        key = f"session:{session_id}:state"
        data = self._get(key)
        if data is None:
            return None
        try:
            return json.loads(_decompress(data))
        except Exception:
            return None

    def set_session_state(self, session_id: str, state: dict, ttl: int = 3600) -> None:
        key = f"session:{session_id}:state"
        data = _compress(json.dumps(state, default=str))
        self._set(key, data, ttl)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict:
        return {
            "lru": self._lru.stats,
            "redis": self._redis.available if self._redis else False,
            "crawl_ttl": self._crawl_ttl,
            "lead_ttl": self._lead_ttl,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get(self, key: str) -> bytes | None:
        # L1
        data = self._lru.get(key)
        if data is not None:
            return data
        # L2
        if self._redis and self._redis.available:
            data = self._redis.get(key)
            if data is not None:
                # Warm L1
                self._lru.set(key, data)
                return data
        return None

    def _set(self, key: str, data: bytes, ttl: int) -> None:
        self._lru.set(key, data, ttl)
        if self._redis and self._redis.available:
            self._redis.set(key, data, ttl)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config) -> LeadCache:
        """Create a ``LeadCache`` from ``AppConfig``."""
        session_cfg = config.session
        redis_url = session_cfg.redis_url if session_cfg.redis_enabled else None
        inst = cls.__new__(cls)
        inst._lru = _LRUCache(maxsize=session_cfg.lru_maxsize)
        inst._crawl_ttl = session_cfg.crawl_cache_ttl
        inst._lead_ttl = session_cfg.lead_cache_ttl
        if redis_url:
            inst._redis = _RedisBackend(
                url=redis_url,
                pool_size=getattr(session_cfg, "redis_pool_size", 20),
                socket_timeout=getattr(session_cfg, "redis_socket_timeout", 5),
                retry_on_timeout=getattr(session_cfg, "redis_retry_on_timeout", True),
            )
        else:
            inst._redis = None
        return inst


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _crawl_key(url: str) -> str:
    return "crawl:" + hashlib.sha256(url.encode()).hexdigest()[:24]


def _lead_key(domain: str) -> str:
    return f"lead:{domain}"


def _compress(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"), compresslevel=6)


def _decompress(data: bytes) -> str:
    return gzip.decompress(data).decode("utf-8")


def _serialize_page(page) -> bytes:
    """Serialize a CrawledPage to compact gzip JSON (excludes links for size)."""
    d = {
        "url": page.url,
        "final_url": page.final_url,
        "status_code": page.status_code,
        "title": page.title,
        "text_content": page.text_content,
        "crawled_at": page.crawled_at,
        "latency_ms": page.latency_ms,
        "success": page.success,
        "error": page.error,
        # Meta
        "emails": page.meta.emails,
        "phone_numbers": page.meta.phone_numbers,
        "social_links": page.meta.social_links,
        "tech_signals": page.meta.tech_signals,
        "og_site_name": page.meta.og_site_name,
        "description": page.meta.description,
        "json_ld": page.meta.json_ld,
        "canonical_url": page.meta.canonical_url,
    }
    return _compress(json.dumps(d, ensure_ascii=False))


def _deserialize_page(data: bytes):
    from discovery.crawler import CrawledPage, ExtractedMeta

    d = json.loads(_decompress(data))
    meta = ExtractedMeta(
        emails=d.get("emails", []),
        phone_numbers=d.get("phone_numbers", []),
        social_links=d.get("social_links", {}),
        tech_signals=d.get("tech_signals", []),
        og_site_name=d.get("og_site_name", ""),
        description=d.get("description", ""),
        json_ld=d.get("json_ld", []),
        canonical_url=d.get("canonical_url", ""),
    )
    return CrawledPage(
        url=d["url"],
        final_url=d["final_url"],
        status_code=d["status_code"],
        title=d["title"],
        text_content=d["text_content"],
        meta=meta,
        links=[],  # not cached to save space
        crawled_at=d["crawled_at"],
        latency_ms=d["latency_ms"],
        success=d["success"],
        error=d.get("error"),
    )
