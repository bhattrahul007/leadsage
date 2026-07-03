from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import ClassVar, Literal, TypedDict
from urllib.parse import urlparse

import requests

from common.retry import RetryConfig, retry_with_config


class SearchResultMetadata(TypedDict, total=False):
    """
    Optional rich metadata captured from each provider's raw response.
    All fields are optional — only set what the API actually returns.

    Field guide
    -----------
    published_date   ISO 8601 publication/crawl date.
    score            Provider's relevance confidence (0-1, Tavily).
    raw_content      Full page text (Tavily advanced depth).
    image_url        Thumbnail or hero image URL.
    displayed_link   Human-readable URL shown in SERP ("example.com › blog").
    site_links       Sub-page links listed under the main result.
    attributes       Structured key-value pairs from knowledge panel (Serper).
    page_map         Google pagemap — OpenGraph, schema.org, metatags, hcard.
    rating           Aggregate business / product rating.
    rating_count     Number of ratings.
    address          Physical address for local / business results.
    phone            Phone number for local / business results.
    answer_box       Featured snippet / direct answer content.
    knowledge_graph  Entity knowledge panel (company, person, place, etc.).
    related_searches "People also search for" suggestions.
    total_results    Provider's estimate of total matching pages.
    """

    published_date: str
    score: float
    raw_content: str
    image_url: str
    displayed_link: str
    site_links: list[dict[str, str]]
    attributes: dict[str, str]
    page_map: dict
    rating: float
    rating_count: int
    address: str
    phone: str
    answer_box: dict
    knowledge_graph: dict
    related_searches: list[str]
    total_results: str


class SearchResult(TypedDict):
    """
    Normalized, enriched result returned by every provider.

    Core fields are always present.
    ``metadata`` holds provider-specific extras; may be an empty dict.
    """

    title: str
    href: str
    body: str
    domain: str  # Extracted from href — always present, e.g. "example.com"
    rank: int  # 1-indexed position within the provider's result list
    provider: str  # Provider slug, e.g. "serper"
    query: str  # The query string that produced this result
    search_type: str  # "web" or "news"
    fetched_at: str  # ISO 8601 UTC timestamp
    metadata: SearchResultMetadata


# ---------------------------------------------------------------------------
# Search configuration
# ---------------------------------------------------------------------------


@dataclass
class SearchConfig:
    """
    Unified input configuration for all search providers.

    Attributes:
        max_results:     Maximum results per provider call.
        page:            1-indexed page number (pagination support).
        country:         ISO 3166-1 alpha-2 country code, e.g. "us".
        language:        ISO 639-1 language code, e.g. "en".
        time_range:      Recency filter; provider-specific syntax, e.g. "qdr:w".
        include_domains: Restrict results to these domains.
        exclude_domains: Strip results from these domains.
        search_type:     "web" (default) or "news".
        search_depth:    "basic" or "advanced" — Tavily-specific.
        topic:           Category — Tavily-specific, e.g. "general", "news".
        safe_search:     Enable provider-level safe-search.
        timeout:         HTTP timeout per request in seconds.
        retries:         Retry attempts on transient failures (5xx, 429, timeout).
        retry_backoff:   Base seconds for exponential backoff between retries.
    """

    max_results: int = 10
    page: int = 1
    country: str | None = None
    language: str | None = None
    time_range: str | None = None
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    search_type: Literal["web", "news"] = "web"
    search_depth: Literal["basic", "advanced"] = "basic"
    topic: str = "general"
    safe_search: bool = True
    timeout: int = 20
    retries: int = 2
    retry_backoff: float = 1.0


class BaseSearchProvider(ABC):
    """
    Abstract base all search providers must implement.

    Subclass contract
    -----------------
    - ``name``    ClassVar[str] — unique slug, e.g. "serper"
    - ``env_key`` ClassVar[str] — env-var name for the primary API key
    - ``search() -> list[SearchResult]``

    Override ``_load_api_key()`` for providers that need multiple keys
    (e.g. Google requires both GOOGLE_API_KEY and GOOGLE_CX_KEY).
    """

    name: ClassVar[str]
    env_key: ClassVar[str]

    def __init__(self, query: str, config: SearchConfig | None = None) -> None:
        self.query = query
        self.config = config or SearchConfig()
        self.logger = logging.getLogger(f"discovery.{self.name}")
        self.api_key = self._load_api_key()

    def _load_api_key(self) -> str:
        from common.secrets import KeyRing

        ring = KeyRing(self.env_key)
        if not ring.available:
            raise OSError(
                f"[{self.name}] API key missing. Set the {self.env_key!r} environment variable."
            )
        return ring.next_key()

    @abstractmethod
    def search(self) -> list[SearchResult]:
        """Execute the search and return normalized, enriched results."""
        ...

    def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> requests.Response:
        """
        Send an HTTP request wrapped in the ``@retry`` decorator.

        Retries on: ConnectionError, Timeout, 429, 5xx.
        Raises immediately on: 4xx other than 429 (non-retryable).

        The retry policy is driven by ``SearchConfig.retries`` and
        ``SearchConfig.retry_backoff``. Jitter and all other behaviour
        come from :class:`~discovery.retry.RetryConfig`.
        """
        cfg = self.config

        def _is_retryable(exc: Exception) -> bool:
            """Only retry transient network failures and server errors."""
            if isinstance(exc, requests.HTTPError):
                code = getattr(getattr(exc, "response", None), "status_code", 0)
                return code == 429 or code >= 500
            return True  # ConnectionError / Timeout are always retryable

        retry_cfg = RetryConfig(
            max_attempts=cfg.retries + 1,
            backoff=cfg.retry_backoff,
            base=2.0,
            max_wait=cfg.timeout * 2.0,
            jitter="equal",
            exceptions=(
                requests.ConnectionError,
                requests.Timeout,
                requests.HTTPError,
            ),
            predicate=_is_retryable,
            on_retry=lambda s: self.logger.warning(
                "Attempt %d/%d failed (%s). Retrying in %.2fs.",
                s.attempt,
                s.max_attempts,
                s.last_exception,
                s.next_wait,
            ),
            on_exhausted=lambda s: self.logger.error(
                "All %d attempts exhausted for %s: %s",
                s.max_attempts,
                url,
                s.last_exception,
            ),
            logger=self.logger,
        )

        @retry_with_config(retry_cfg)
        def _do() -> requests.Response:
            resp = requests.request(method, url, timeout=cfg.timeout, **kwargs)
            # Non-retryable 4xx — raise immediately (predicate will block retry)
            if resp.status_code != 429 and 400 <= resp.status_code < 500:
                resp.raise_for_status()
            # Retryable: 429 rate-limit or 5xx server error
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"Retryable HTTP {resp.status_code}", response=resp)
            return resp

        return _do()

    def _build_result(
        self,
        *,
        rank: int,
        title: str,
        href: str,
        body: str,
        metadata: SearchResultMetadata | None = None,
    ) -> SearchResult:
        """Build a fully-populated SearchResult from provider raw fields."""
        return SearchResult(
            title=title.strip(),
            href=href,
            body=body.strip(),
            domain=_extract_domain(href),
            rank=rank,
            provider=self.name,
            query=self.query,
            search_type=self.config.search_type,
            fetched_at=_utc_now(),
            metadata=metadata or {},
        )

    @staticmethod
    def _is_junk(url: str, skip_hosts: tuple[str, ...] = ("youtube.com",)) -> bool:
        """Return True for URLs we always skip (e.g. YouTube)."""
        return any(h in url for h in skip_hosts)


def _extract_domain(url: str) -> str:
    """Extract bare hostname (no www.) from a URL string."""
    try:
        netloc = urlparse(url).netloc
        return netloc.removeprefix("www.")
    except Exception:
        return ""


def _utc_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()
