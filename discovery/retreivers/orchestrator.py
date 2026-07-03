from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from datetime import UTC, datetime
import gzip
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING

from discovery.retreivers.base import SearchConfig, SearchResult
from discovery.retreivers.models import ProviderResponse, SearchSession
from discovery.retreivers.registry import get_provider, list_providers

if TYPE_CHECKING:
    from common.session.cache import LeadCache

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """
    Configuration for SearchOrchestrator.

    Attributes:
        providers:    Provider slugs to query. Defaults to all registered.
        max_workers:  Thread pool size (I/O-bound — set higher than CPU count).
    """

    providers: list[str] = field(default_factory=list)
    max_workers: int = 5

    def __post_init__(self) -> None:
        if not self.providers:
            self.providers = list_providers()


class SearchOrchestrator:
    """
    Executes a query against multiple search providers concurrently
    and returns a fully populated ``SearchSession``.

    Example
    -------
    ::

        orchestrator = SearchOrchestrator(
            OrchestratorConfig(providers=["serper", "tavily", "bing"])
        )
        session = orchestrator.search(
            "fintech SaaS companies outsourcing engineering",
            search_config=SearchConfig(max_results=10, country="us"),
        )
        print(session)                      # quick summary
        print(session.top_results(10))      # re-ranked, deduped
        print(session.domain_frequency())   # ICP signal heatmap
        print(session.provider_summary())   # latency + health per provider
    """

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        cache: LeadCache | None = None,
    ) -> None:
        self.config = config or OrchestratorConfig()
        self._cache = cache

    def search(
        self,
        query: str,
        search_config: SearchConfig | None = None,
    ) -> SearchSession:
        """
        Fan-out ``query`` to all configured providers concurrently.

        Args:
            query:         The search query string.
            search_config: Shared ``SearchConfig`` applied to every provider.

        Returns:
            A ``SearchSession`` with all provider responses and analytics.
        """
        cfg = search_config or SearchConfig()
        responses: list[ProviderResponse] = []

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.config.max_workers,
            thread_name_prefix="discovery_worker",
        ) as pool:
            future_to_name: dict[concurrent.futures.Future, str] = {
                pool.submit(self._call_provider_cached, name, query, cfg): name
                for name in self.config.providers
            }

            for future in concurrent.futures.as_completed(future_to_name):
                provider_name = future_to_name[future]
                try:
                    response = future.result()
                    responses.append(response)
                    logger.info(
                        "[%s] %d results in %.0fms",
                        provider_name,
                        response.result_count,
                        response.latency_ms,
                    )
                except Exception as exc:
                    logger.error("[%s] unexpected orchestrator error: %s", provider_name, exc)
                    responses.append(
                        ProviderResponse(
                            provider=provider_name,
                            query=query,
                            results=[],
                            latency_ms=0.0,
                            fetched_at=datetime.now(UTC),
                            success=False,
                            error=str(exc),
                        )
                    )

        return SearchSession(query=query, config=cfg, responses=responses)

    def _call_provider_cached(
        self,
        name: str,
        query: str,
        config: SearchConfig,
    ) -> ProviderResponse:
        """Call provider with L2 cache check and rate-limit gate."""
        from common.ratelimit import RateLimiterRegistry

        RateLimiterRegistry.acquire(name)

        cache_key = _search_cache_key(name, query, config.max_results)
        if self._cache:
            cached = self._cache._get(cache_key)
            if cached:
                try:
                    data = json.loads(gzip.decompress(cached).decode())
                    results: list[SearchResult] = data["results"]
                    logger.debug("[%s] search cache hit (%s)", name, query[:40])
                    return ProviderResponse(
                        provider=name,
                        query=query,
                        results=results,
                        latency_ms=0.0,
                        fetched_at=datetime.now(UTC),
                        success=True,
                        total_results=len(results),
                    )
                except Exception:
                    pass

        response = self._call_provider(name, query, config)

        if response.success and self._cache:
            try:
                payload = gzip.compress(
                    json.dumps(
                        {"results": response.results},
                        ensure_ascii=False,
                        default=str,
                    ).encode()
                )
                self._cache._set(cache_key, payload, ttl=3600)
            except Exception:
                pass

        return response

    @staticmethod
    def _call_provider(
        name: str,
        query: str,
        config: SearchConfig,
    ) -> ProviderResponse:
        """Call one provider and wrap its output in a ProviderResponse."""
        start = time.perf_counter()
        fetched_at = datetime.now(UTC)
        try:
            results = get_provider(name, query, config).search()
            latency_ms = (time.perf_counter() - start) * 1000
            return ProviderResponse(
                provider=name,
                query=query,
                results=results,
                latency_ms=latency_ms,
                fetched_at=fetched_at,
                success=True,
                total_results=len(results),
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error("[%s] search failed: %s", name, exc)
            return ProviderResponse(
                provider=name,
                query=query,
                results=[],
                latency_ms=latency_ms,
                fetched_at=fetched_at,
                success=False,
                error=str(exc),
            )


def _search_cache_key(provider: str, query: str, max_results: int) -> str:
    digest = hashlib.sha256(f"{provider}:{query}:{max_results}".encode()).hexdigest()[:20]
    return f"search:{digest}"
