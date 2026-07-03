from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PipelineStarted:
    session_id: str
    query: str
    provider_count: int
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class PipelineCompleted:
    session_id: str
    query: str
    total_leads: int
    hot_count: int
    warm_count: int
    cold_count: int
    pipeline_ms: float
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class PipelineFailed:
    session_id: str
    query: str
    error: str
    stage: str
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class IcpParsed:
    session_id: str
    query: str
    confidence: float
    industries: list[str]
    technologies: list[str]
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class QueryPlanned:
    session_id: str
    query_count: int
    signal_types: list[str]
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class SearchStarted:
    session_id: str
    query_string: str
    provider: str
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class SearchCompleted:
    session_id: str
    query_string: str
    provider: str
    result_count: int
    latency_ms: float
    success: bool
    error: str | None = None
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class CrawlStarted:
    session_id: str
    url: str
    crawler_type: str
    using_proxy: bool = False
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class CrawlCompleted:
    session_id: str
    url: str
    success: bool
    status_code: int
    latency_ms: float
    word_count: int = 0
    tech_signals: int = 0
    from_cache: bool = False
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class CrawlFailed:
    session_id: str
    url: str
    error: str
    attempt: int
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ProxyAcquired:
    session_id: str
    proxy_host: str
    provider: str
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ProxyRotated:
    session_id: str
    old_proxy: str
    new_proxy: str
    reason: str
    provider: str
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ProxyFailed:
    session_id: str
    proxy_host: str
    error: str
    provider: str
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LeadEnriched:
    session_id: str
    domain: str
    company_name: str
    icp_score: float
    tech_count: int
    hiring_count: int
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LeadScored:
    session_id: str
    domain: str
    company_name: str
    tier: str  # "hot" | "warm" | "cold"
    icp_score: float
    llm_model: str
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class LeadSkipped:
    """A lead was skipped (below min_score or already in cache)."""

    session_id: str
    domain: str
    reason: str  # "below_threshold" | "cached" | "duplicate"
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class CacheHit:
    session_id: str
    cache_key: str
    cache_type: str  # "crawl" | "lead" | "session"
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class CacheMiss:
    session_id: str
    cache_key: str
    cache_type: str
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class SessionCreated:
    session_id: str
    query: str
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class SessionResumed:
    session_id: str
    query: str
    leads_already_found: int
    timestamp: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class MemoryEvicted:
    """Fired when LRU in-memory cache evicts an entry."""

    cache_type: str
    key: str
    reason: str = "lru_eviction"
    timestamp: datetime = field(default_factory=_now)


ALL_EVENT_TYPES: tuple[type, ...] = (
    PipelineStarted,
    PipelineCompleted,
    PipelineFailed,
    IcpParsed,
    QueryPlanned,
    SearchStarted,
    SearchCompleted,
    CrawlStarted,
    CrawlCompleted,
    CrawlFailed,
    ProxyAcquired,
    ProxyRotated,
    ProxyFailed,
    LeadEnriched,
    LeadScored,
    LeadSkipped,
    CacheHit,
    CacheMiss,
    SessionCreated,
    SessionResumed,
    MemoryEvicted,
)
