from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from discovery.retreivers.base import SearchConfig, SearchResult


@dataclass
class ProviderResponse:
    """
    The full result of a single provider call.

    Attributes:
        provider:      Provider slug.
        query:         Query string used.
        results:       Normalized results returned by the provider.
        latency_ms:    Wall-clock time in milliseconds for the call.
        fetched_at:    UTC timestamp when the call completed.
        success:       False if the provider raised an exception.
        error:         Exception message if success is False.
        total_results: Provider-reported total available results (if exposed).
    """

    provider: str
    query: str
    results: list[SearchResult]
    latency_ms: float
    fetched_at: datetime
    success: bool
    error: str | None = None
    total_results: int = 0

    @property
    def result_count(self) -> int:
        return len(self.results)


_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "utm_id",
        "ref",
        "fbclid",
        "gclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
    }
)


@dataclass
class SearchSession:
    """
    Aggregated results from one query run across one or more providers.

    Use this as your primary return type — it carries everything you need
    for downstream analytics, debugging, and ICP signal extraction.

    Attributes:
        session_id:  Auto-generated UUID.
        query:       Original query string.
        config:      SearchConfig used for this session.
        responses:   One ProviderResponse per provider queried.
        created_at:  UTC timestamp when the session was created.
    """

    query: str
    config: SearchConfig
    responses: list[ProviderResponse]
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def all_results(self) -> list[SearchResult]:
        """Flat list of all results from all providers, in order received."""
        out: list[SearchResult] = []
        for r in self.responses:
            out.extend(r.results)
        return out

    def top_results(self, n: int = 10) -> list[SearchResult]:
        """
        Return top-n results after deduplication and cross-provider boosting.
        Results appearing in more providers rank higher.
        """
        return _merge_and_rank(self.all_results)[:n]

    def results_by_provider(self) -> dict[str, list[SearchResult]]:
        """Map of provider slug → its results."""
        return {r.provider: r.results for r in self.responses}

    @property
    def successful_providers(self) -> list[str]:
        return [r.provider for r in self.responses if r.success]

    @property
    def failed_providers(self) -> list[str]:
        return [r.provider for r in self.responses if not r.success]

    @property
    def success_rate(self) -> float:
        if not self.responses:
            return 0.0
        return len(self.successful_providers) / len(self.responses)

    @property
    def total_latency_ms(self) -> float:
        """Sum of all per-provider latencies (parallel calls overlap in wall time)."""
        return sum(r.latency_ms for r in self.responses)

    @property
    def slowest_provider(self) -> str | None:
        if not self.responses:
            return None
        return max(self.responses, key=lambda r: r.latency_ms).provider

    @property
    def fastest_provider(self) -> str | None:
        if not self.responses:
            return None
        return min(self.responses, key=lambda r: r.latency_ms).provider

    def domain_frequency(self) -> dict[str, int]:
        """
        Count how many times each domain appears across all results.

        High-frequency domains = strong signal for ICP targets.
        E.g. if 3 providers all surface 'acmecorp.com', it's a hot lead.
        """
        freq: dict[str, int] = {}
        for r in self.all_results:
            domain = r["domain"]
            if domain:
                freq[domain] = freq.get(domain, 0) + 1
        return dict(sorted(freq.items(), key=lambda x: -x[1]))

    def cross_provider_hits(self, min_providers: int = 2) -> list[SearchResult]:
        """
        Return deduplicated results that appeared in at least ``min_providers``
        different providers — the highest-confidence signal set.
        """
        url_providers: dict[str, set[str]] = {}
        url_result: dict[str, SearchResult] = {}

        for r in self.all_results:
            key = _normalize_url(r["href"])
            url_providers.setdefault(key, set()).add(r["provider"])
            url_result.setdefault(key, r)

        return [
            url_result[k]
            for k, providers in url_providers.items()
            if len(providers) >= min_providers
        ]

    def provider_summary(self) -> list[dict]:
        """Per-provider stats list — useful for logging / dashboards."""
        return [
            {
                "provider": r.provider,
                "success": r.success,
                "results": r.result_count,
                "latency_ms": round(r.latency_ms, 1),
                "error": r.error,
                "total_available": r.total_results,
            }
            for r in self.responses
        ]

    def to_dict(self) -> dict:
        """Serialize the full session to a plain dict (JSON-safe)."""
        return {
            "session_id": self.session_id,
            "query": self.query,
            "created_at": self.created_at.isoformat(),
            "success_rate": self.success_rate,
            "provider_summary": self.provider_summary(),
            "domain_frequency": self.domain_frequency(),
            "results": list(self.top_results(n=len(self.all_results))),
        }

    def __repr__(self) -> str:
        return (
            f"<SearchSession query={self.query!r} "
            f"providers={len(self.responses)} "
            f"results={len(self.all_results)} "
            f"success_rate={self.success_rate:.0%}>"
        )


def _normalize_url(url: str) -> str:
    """
    Strip tracking params, trailing slash, and fragment for stable dedup.

    Two URLs that render the same page but differ only by UTM params
    are considered identical.
    """
    try:
        parsed = urlparse(url.rstrip("/"))
        clean_params = {
            k: v for k, v in parse_qs(parsed.query).items() if k not in _TRACKING_PARAMS
        }
        clean_query = urlencode(clean_params, doseq=True)
        return urlunparse(parsed._replace(query=clean_query, fragment=""))
    except Exception:
        return url


def _merge_and_rank(results: list[SearchResult]) -> list[SearchResult]:
    """
    Deduplicate by normalized URL and re-rank:

    Primary key:   number of distinct providers that returned the same URL
                   (more = higher confidence signal)
    Secondary key: average rank across providers (lower = better)
    """
    url_results: dict[str, list[SearchResult]] = {}
    for r in results:
        key = _normalize_url(r["href"])
        url_results.setdefault(key, []).append(r)

    merged: list[tuple[SearchResult, int, float]] = []
    for group in url_results.values():
        best = group[0]
        provider_count = len({r["provider"] for r in group})
        avg_rank = sum(r["rank"] for r in group) / len(group)
        merged.append((best, provider_count, avg_rank))

    merged.sort(key=lambda x: (-x[1], x[2]))
    return [item[0] for item in merged]
