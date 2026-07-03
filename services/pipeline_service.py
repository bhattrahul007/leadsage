from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common.config import AppConfig
    from common.events.bus import EventBus
    from common.session.cache import LeadCache
    from discovery.pipeline import PipelineResult

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    session_id: str
    query: str
    scored_leads: list  # list[ScoredLead]
    pipeline_result: PipelineResult
    wall_ms: float
    tier_counts: dict[str, int] = field(default_factory=dict)


class PipelineService:
    """
    Orchestrates the full lead generation run.

    Decoupled from CLI/HTTP transport so it can be used from
    the command line, FastAPI routes, or Celery tasks unchanged.
    """

    def __init__(
        self,
        config: AppConfig,
        bus: EventBus | None = None,
        cache: LeadCache | None = None,
    ) -> None:
        self._cfg = config
        self._bus = bus
        self._cache = cache

    def run(self, query: str, session_id: str | None = None) -> RunResult:
        wall_start = time.perf_counter()
        cfg = self._cfg

        from agents import AgentFactory
        from common.session import SessionManager

        sess_mgr = SessionManager.from_config(cfg, cache=self._cache)
        session = sess_mgr.get_or_create(query, session_id=session_id)
        self._emit_session_event(session, query)

        icp_agent = AgentFactory.create("icp_parser", cfg, bus=self._bus, session=session)
        icp = icp_agent.parse(query)
        logger.info(
            "ICP: industries=%s tech=%s titles=%s confidence=%.2f",
            icp.target_company.industries[:3],
            icp.technologies.required[:3],
            icp.buyer_persona.titles[:3],
            icp.confidence,
        )

        proxy_provider = None
        if cfg.proxy.enabled:
            from common.proxy import ProxyProviderFactory

            proxy_provider = ProxyProviderFactory.create(cfg.proxy)

        from discovery.pipeline import DiscoveryPipeline

        pipeline = DiscoveryPipeline(
            config=_make_pipe_config(cfg),
            bus=self._bus,
            cache=self._cache,
            proxy_provider=proxy_provider,
            session_id=session.id,
        )
        result = pipeline.run(icp)

        if not result.leads:
            sess_mgr.mark_completed(session.id, total_leads=0)
            return RunResult(
                session_id=session.id,
                query=query,
                scored_leads=[],
                pipeline_result=result,
                wall_ms=(time.perf_counter() - wall_start) * 1000,
            )

        top_enriched = result.top_leads(cfg.output.top_leads * 2)
        scorer = AgentFactory.create(
            "lead_scorer",
            cfg,
            bus=self._bus,
            session=session,
            icp=icp,
            hot_threshold=cfg.scoring.hot_threshold,
            warm_threshold=cfg.scoring.warm_threshold,
            llm_enabled=cfg.scoring.llm_enabled,
        )
        scored = scorer.run(
            enriched_leads=top_enriched,
            max_workers=cfg.scoring.max_concurrent_scorers,
        )
        top_scored = scored[: cfg.output.top_leads]

        if cfg.scoring.research_hot_leads:
            self._run_research(session, top_scored, result)

        if cfg.scoring.find_contacts:
            self._run_contact_finding(session, top_scored, result)

        tier_counts = Counter(s.lead_tier.value for s in top_scored)
        sess_mgr.mark_completed(
            session.id,
            total_leads=len(top_scored),
            hot_count=tier_counts["hot"],
            warm_count=tier_counts["warm"],
            cold_count=tier_counts["cold"],
            pipeline_ms=result.pipeline_ms,
        )

        return RunResult(
            session_id=session.id,
            query=query,
            scored_leads=top_scored,
            pipeline_result=result,
            wall_ms=(time.perf_counter() - wall_start) * 1000,
            tier_counts=dict(tier_counts),
        )

    def _run_research(self, session, scored: list, result: PipelineResult) -> None:
        from agents import AgentFactory
        from common.session import MemoryManager

        hot = [s for s in scored if s.lead_tier.value == "hot"]
        if not hot:
            return
        researcher = AgentFactory.create("research", self._cfg, bus=self._bus, session=session)
        mem = MemoryManager.from_config(self._cfg)
        domain_pages = _group_pages_by_domain(result.crawled_pages)
        for lead in hot[:5]:
            pages = domain_pages.get(lead.domain, [])
            if not pages:
                continue
            profile = researcher.research(lead.domain, pages)
            if profile.description and not lead.company_summary:
                lead.company_summary = profile.description
            if profile.pitch_angle and not lead.why_this_lead:
                lead.why_this_lead = profile.pitch_angle
            mem.store_summary(session.id, lead.source_url, profile.description)

    def _run_contact_finding(self, session, scored: list, result: PipelineResult) -> None:
        from agents import AgentFactory

        contact_agent = AgentFactory.create(
            "contact_finder", self._cfg, bus=self._bus, session=session
        )
        domain_pages = _group_pages_by_domain(result.crawled_pages)
        for lead in scored[:10]:
            pages = domain_pages.get(lead.domain, [])
            if pages and not lead.decision_makers:
                contacts = contact_agent.find_contacts(lead.domain, pages)
                if contacts:
                    lead.decision_makers = contacts

    def _emit_session_event(self, session, query: str) -> None:
        from common.events.events import SessionCreated, SessionResumed

        if not self._bus:
            return
        if session.total_leads == 0:
            self._bus.publish(SessionCreated(session_id=session.id, query=query))
        else:
            self._bus.publish(
                SessionResumed(
                    session_id=session.id,
                    query=query,
                    leads_already_found=session.total_leads,
                )
            )


def _make_pipe_config(cfg: AppConfig):
    from discovery.pipeline import PipelineConfig

    p = cfg.pipeline
    return PipelineConfig(
        providers=p.providers,
        crawler_type=p.crawler_type,
        max_results_per_query=p.max_results_per_query,
        search_workers=p.search_workers,
        crawl_enabled=p.crawl_enabled,
        max_urls_to_crawl=p.max_urls_to_crawl,
        crawl_workers=p.crawl_workers,
        crawl_timeout=p.crawl_timeout,
        domain_delay=p.domain_delay,
        enrich_enabled=p.enrich_enabled,
        min_lead_score=p.min_lead_score,
        skip_domains=p.skip_domains,
        prefer_domains=p.prefer_domains,
        pages_per_domain=p.pages_per_domain,
        signal_paths=p.signal_paths,
    )


def _group_pages_by_domain(pages) -> dict[str, list]:
    groups: dict[str, list] = {}
    for page in pages:
        if page.success:
            groups.setdefault(page.domain, []).append(page)
    return groups
