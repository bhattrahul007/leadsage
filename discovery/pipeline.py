from __future__ import annotations

import concurrent.futures
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from common.schemas.icp_request import IcpDiscoveryQuery
from discovery.retreivers.base import SearchConfig, SearchResult
from discovery.crawler import CrawledPage, CrawlerConfig, WebCrawler
from discovery.enricher import EnricherConfig, EnrichedLead, LeadEnricher
from discovery.retreivers.models import SearchSession, _normalize_url
from discovery.retreivers.orchestrator import OrchestratorConfig, SearchOrchestrator
from discovery.query_planner import PlannedQuery, QueryPlan, QueryPlanner

if TYPE_CHECKING:
    from common.events.bus import EventBus
    from common.session.cache import LeadCache
    from discovery.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Full pipeline configuration (mirrors PipelineSettings in common.config)."""

    # search
    providers: list[str] = field(default_factory=list)
    max_results_per_query: int = 10
    search_workers: int = 5

    # crawler
    crawler_type: str = "requests"  # "requests" | "playwright"
    crawl_enabled: bool = True
    max_urls_to_crawl: int = 30
    crawl_workers: int = 10
    crawl_timeout: int = 15
    domain_delay: float = 0.0

    # enrich
    enrich_enabled: bool = True
    min_lead_score: float = 0.15

    # Multi-page per domain
    pages_per_domain: int = 1
    signal_paths: list[str] = field(
        default_factory=lambda: ["/", "/about", "/careers", "/technology"]
    )

    # URL selection
    skip_domains: list[str] = field(
        default_factory=lambda: [
            "youtube.com",
            "twitter.com",
            "x.com",
            "facebook.com",
            "instagram.com",
            "tiktok.com",
            "reddit.com",
            "wikipedia.org",
            "linkedin.com",
        ]
    )
    prefer_domains: list[str] = field(
        default_factory=lambda: [
            "crunchbase.com",
            "glassdoor.com",
            "builtwith.com",
            "stackshare.io",
            "techcrunch.com",
        ]
    )


@dataclass
class StageMetrics:
    stage: str
    started_at: datetime
    completed_at: datetime | None = None
    items_in: int = 0
    items_out: int = 0
    error_count: int = 0

    @property
    def latency_ms(self) -> float:
        if self.completed_at is None:
            return 0.0
        return (self.completed_at - self.started_at).total_seconds() * 1000

    def finish(self, items_out: int, error_count: int = 0) -> None:
        self.completed_at = datetime.now(timezone.utc)
        self.items_out = items_out
        self.error_count = error_count


@dataclass
class PipelineResult:
    icp: IcpDiscoveryQuery
    query_plan: QueryPlan
    search_sessions: list[SearchSession]
    crawled_pages: list[CrawledPage]
    leads: list[EnrichedLead]
    stage_metrics: list[StageMetrics]
    pipeline_ms: float
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def top_leads(self, n: int = 20) -> list[EnrichedLead]:
        return sorted(self.leads, key=lambda l: -l.icp_relevance_score)[:n]

    @property
    def all_search_results(self) -> list[SearchResult]:
        out: list[SearchResult] = []
        for session in self.search_sessions:
            out.extend(session.all_results)
        return out

    @property
    def unique_domains(self) -> list[str]:
        seen: dict[str, float] = {}
        for lead in self.leads:
            if lead.domain not in seen:
                seen[lead.domain] = lead.icp_relevance_score
        return sorted(seen, key=lambda d: -seen[d])

    @property
    def crawl_success_rate(self) -> float:
        if not self.crawled_pages:
            return 0.0
        return sum(1 for p in self.crawled_pages if p.success) / len(self.crawled_pages)

    def summary(self) -> dict:
        stage_data = [
            {
                "stage": m.stage,
                "latency_ms": round(m.latency_ms, 1),
                "in": m.items_in,
                "out": m.items_out,
                "errors": m.error_count,
            }
            for m in self.stage_metrics
        ]
        return {
            "query": self.icp.original_query,
            "planned_queries": len(self.query_plan),
            "search_sessions": len(self.search_sessions),
            "total_results": len(self.all_search_results),
            "crawled_pages": len(self.crawled_pages),
            "crawl_success_rate": round(self.crawl_success_rate, 2),
            "leads": len(self.leads),
            "top_lead_score": round(self.leads[0].icp_relevance_score, 3) if self.leads else 0.0,
            "pipeline_ms": round(self.pipeline_ms, 1),
            "stages": stage_data,
        }

    def __repr__(self) -> str:
        return (
            f"<PipelineResult leads={len(self.leads)} "
            f"crawled={len(self.crawled_pages)} "
            f"pipeline_ms={self.pipeline_ms:.0f}>"
        )


class DiscoveryPipeline:
    """Orchestrates the full ICP → leads pipeline.

    Stages: Plan → Search → Merge → Crawl → Enrich.
    Pass an EventBus to receive typed events at every stage.
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        bus: "EventBus | None" = None,
        cache: "LeadCache | None" = None,
        proxy_provider=None,
        session_id: str = "default",
    ) -> None:
        self.config = config or PipelineConfig()
        self._bus = bus
        self._cache = cache
        self._proxy = proxy_provider
        self._session_id = session_id
        self._planner = QueryPlanner()

        # Build crawler from factory
        crawler_config = CrawlerConfig(
            timeout=self.config.crawl_timeout,
            domain_delay_seconds=self.config.domain_delay,
        )
        self._crawler = self._build_crawler(crawler_config)

    def _build_crawler(self, crawler_config: CrawlerConfig) -> "BaseCrawler":
        from discovery.crawlers import CrawlerFactory

        crawler_type = self.config.crawler_type

        if self._proxy:
            logger.info("Crawler: %s + proxy(%s)", crawler_type, self._proxy.name)
            return CrawlerFactory.create_with_proxy(crawler_type, crawler_config, self._proxy)
        logger.info("Crawler: %s (no proxy)", crawler_type)
        return CrawlerFactory.create(crawler_type, crawler_config)

    def run(self, icp: IcpDiscoveryQuery) -> PipelineResult:
        wall_start = time.perf_counter()
        metrics: list[StageMetrics] = []
        cfg = self.config

        self._publish_start(icp)

        m = _start_stage("plan")
        plan = self._planner.plan(icp)
        m.finish(items_in=1, items_out=len(plan))
        metrics.append(m)
        logger.info("[pipeline] plan: %d queries", len(plan))
        self._publish_plan(plan)

        m = _start_stage("search")
        m.items_in = len(plan)
        sessions = self._run_search_stage(plan)
        m.finish(
            items_out=sum(len(s.all_results) for s in sessions),
            error_count=sum(len(s.failed_providers) for s in sessions),
        )
        metrics.append(m)
        logger.info("[pipeline] search: %d sessions, %d raw results", len(sessions), m.items_out)

        m = _start_stage("merge")
        m.items_in = m.items_out
        url_result_map = self._merge_results(sessions)
        urls_to_crawl = self._select_urls(list(url_result_map.keys()), cfg)
        m.finish(items_out=len(urls_to_crawl))
        metrics.append(m)

        crawled_pages: list[CrawledPage] = []
        if cfg.crawl_enabled and urls_to_crawl:
            m = _start_stage("crawl")
            m.items_in = len(urls_to_crawl)
            crawled_pages = self._run_crawl_stage(urls_to_crawl)
            ok = sum(1 for p in crawled_pages if p.success)
            m.finish(items_out=ok, error_count=len(crawled_pages) - ok)
            metrics.append(m)
            logger.info("[pipeline] crawl: %d/%d succeeded", ok, len(crawled_pages))

        leads: list[EnrichedLead] = []
        if cfg.enrich_enabled and crawled_pages:
            m = _start_stage("enrich")
            m.items_in = len(crawled_pages)
            enricher = LeadEnricher(icp, EnricherConfig(min_score=cfg.min_lead_score))
            pairs = [
                (page, url_result_map[page.url])
                for page in crawled_pages
                if page.url in url_result_map
            ]
            leads = enricher.enrich_many(pairs)
            m.finish(items_out=len(leads))
            metrics.append(m)
            logger.info("[pipeline] enrich: %d leads", len(leads))
            self._publish_leads(leads)

        pipeline_ms = (time.perf_counter() - wall_start) * 1000
        logger.info("[pipeline] total %.0fms → %d leads", pipeline_ms, len(leads))
        self._publish_complete(icp, leads, pipeline_ms)

        return PipelineResult(
            icp=icp,
            query_plan=plan,
            search_sessions=sessions,
            crawled_pages=crawled_pages,
            leads=leads,
            stage_metrics=metrics,
            pipeline_ms=pipeline_ms,
        )

    def _run_search_stage(self, plan: QueryPlan) -> list[SearchSession]:
        cfg = self.config

        def _run_query(pq: PlannedQuery) -> SearchSession:
            overrides = pq.config_overrides or {}
            search_cfg = SearchConfig(
                max_results=cfg.max_results_per_query,
                search_type=pq.search_type,
                **overrides,
            )
            providers = pq.providers or cfg.providers
            orchestrator = SearchOrchestrator(
                OrchestratorConfig(providers=providers, max_workers=cfg.search_workers),
                cache=self._cache,
            )
            return orchestrator.search(pq.query_string, search_config=search_cfg)

        sessions: list[SearchSession] = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(plan.queries), cfg.search_workers),
            thread_name_prefix="pipeline_search",
        ) as pool:
            future_map = {pool.submit(_run_query, pq): pq for pq in plan.by_priority()}
            for future in concurrent.futures.as_completed(future_map):
                try:
                    sessions.append(future.result())
                except Exception as exc:
                    pq = future_map[future]
                    logger.error("[pipeline] query failed %r: %s", pq.query_string, exc)
        return sessions

    def _run_crawl_stage(self, urls: list[str]) -> list[CrawledPage]:
        """Crawl URLs, serving cache hits without network requests."""
        cfg = self.config

        # Separate cache hits from URLs to actually crawl
        to_fetch: list[str] = []
        cached_pages: dict[str, CrawledPage] = {}

        for url in urls:
            if self._cache:
                cached = self._cache.get_crawled_page(url)
                if cached:
                    cached_pages[url] = cached
                    self._publish_crawl_cache_hit(url)
                    continue
            to_fetch.append(url)

        # Crawl the rest
        newly_crawled: list[CrawledPage] = []
        if to_fetch:
            newly_crawled = self._crawler.crawl_many(
                to_fetch,
                max_workers=cfg.crawl_workers,
                proxy_provider=self._proxy,
            )
            # Cache successful crawls
            if self._cache:
                for page in newly_crawled:
                    if page.success:
                        self._cache.set_crawled_page(page.url, page)

            self._publish_crawl_events(newly_crawled)

        # Merge: preserve original URL order
        all_by_url = {**cached_pages, **{p.url: p for p in newly_crawled}}
        return [all_by_url[u] for u in urls if u in all_by_url]

    def _merge_results(self, sessions: list[SearchSession]) -> dict[str, SearchResult]:
        seen: dict[str, SearchResult] = {}
        for session in sessions:
            for result in session.all_results:
                norm = _normalize_url(result["href"])
                if norm not in seen:
                    seen[norm] = result
        return {r["href"]: r for r in seen.values()}

    def _select_urls(self, urls: list[str], cfg: PipelineConfig) -> list[str]:
        skip = set(cfg.skip_domains)
        prefer = set(cfg.prefer_domains)
        filtered = [u for u in urls if not any(d in u for d in skip)]
        preferred = [u for u in filtered if any(d in u for d in prefer)]
        rest = [u for u in filtered if u not in set(preferred)]
        selected = (preferred + rest)[: cfg.max_urls_to_crawl]

        if cfg.pages_per_domain > 1:
            selected = _expand_domain_pages(selected, cfg.signal_paths, cfg.pages_per_domain)

        return selected[: cfg.max_urls_to_crawl]

    def _publish(self, event) -> None:
        if self._bus:
            self._bus.publish(event)

    def _publish_start(self, icp: IcpDiscoveryQuery) -> None:
        from common.events.events import PipelineStarted

        self._publish(
            PipelineStarted(
                session_id=self._session_id,
                query=icp.original_query,
                provider_count=len(self.config.providers),
            )
        )

    def _publish_plan(self, plan: QueryPlan) -> None:
        from common.events.events import QueryPlanned

        self._publish(
            QueryPlanned(
                session_id=self._session_id,
                query_count=len(plan),
                signal_types=list(plan.by_signal().keys()),
            )
        )

    def _publish_leads(self, leads: list[EnrichedLead]) -> None:
        from common.events.events import LeadEnriched

        for lead in leads:
            self._publish(
                LeadEnriched(
                    session_id=self._session_id,
                    domain=lead.domain,
                    company_name=lead.company_name,
                    icp_score=lead.icp_relevance_score,
                    tech_count=len(lead.tech_stack),
                    hiring_count=len(lead.hiring_signals),
                )
            )

    def _publish_crawl_cache_hit(self, url: str) -> None:
        from common.events.events import CacheHit

        self._publish(
            CacheHit(
                session_id=self._session_id,
                cache_key=url[:60],
                cache_type="crawl",
            )
        )

    def _publish_crawl_events(self, pages: list[CrawledPage]) -> None:
        from common.events.events import CrawlCompleted

        for page in pages:
            self._publish(
                CrawlCompleted(
                    session_id=self._session_id,
                    url=page.url,
                    success=page.success,
                    status_code=page.status_code,
                    latency_ms=page.latency_ms,
                    word_count=page.word_count if page.success else 0,
                    tech_signals=len(page.meta.tech_signals) if page.success else 0,
                )
            )

    def _publish_complete(self, icp: IcpDiscoveryQuery, leads: list, pipeline_ms: float) -> None:
        from collections import Counter
        from common.events.events import PipelineCompleted

        tiers = Counter(getattr(lead, "lead_tier", {}) for lead in leads)
        self._publish(
            PipelineCompleted(
                session_id=self._session_id,
                query=icp.original_query,
                total_leads=len(leads),
                hot_count=0,  # actual tier counts added after scoring
                warm_count=0,
                cold_count=0,
                pipeline_ms=pipeline_ms,
            )
        )


def _start_stage(name: str) -> StageMetrics:
    return StageMetrics(stage=name, started_at=datetime.now(timezone.utc))


def _expand_domain_pages(urls: list[str], signal_paths: list[str], per_domain: int) -> list[str]:
    """Expand a URL list to include signal pages per domain."""
    from urllib.parse import urlparse, urljoin

    expanded: list[str] = []
    seen_domains: dict[str, int] = {}

    for url in urls:
        domain = urlparse(url).netloc
        count = seen_domains.get(domain, 0)
        if count < per_domain:
            expanded.append(url)
            seen_domains[domain] = count + 1

        # Inject additional signal pages for this domain up to per_domain
        remaining = per_domain - seen_domains.get(domain, 0)
        base = f"https://{domain}"
        for path in signal_paths:
            if remaining <= 0:
                break
            candidate = urljoin(base, path)
            if candidate != url and candidate not in expanded:
                expanded.append(candidate)
                seen_domains[domain] = seen_domains.get(domain, 0) + 1
                remaining -= 1

    return expanded
