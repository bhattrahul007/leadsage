from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="lead-agent",
        description="AI Lead Generation Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("query", nargs="?", help="Natural language ICP query")
    p.add_argument(
        "--config",
        "-c",
        default=None,
        metavar="PATH",
        help="Config JSON path (default: config/config.json)",
    )
    p.add_argument("--output", "-o", default=None, metavar="PATH", help="Output file override")
    p.add_argument("--top", "-n", type=int, default=None, help="Top-N leads in output")
    p.add_argument(
        "--session-id", default=None, metavar="ID", help="Resume an existing session by ID"
    )
    p.add_argument(
        "--proxy",
        default=None,
        metavar="PROVIDER",
        help="Proxy provider override (brightdata|smartproxy|static|none)",
    )
    p.add_argument("--crawler", default=None, help="Crawler override (requests|playwright)")
    p.add_argument(
        "--provider",
        metavar="NAME",
        action="append",
        default=None,
        help="Search provider (repeatable). e.g. --provider serper",
    )
    p.add_argument(
        "--no-llm-scoring", action="store_true", help="Rule-based tier only (no LLM scoring)"
    )
    p.add_argument("--no-crawl", action="store_true", help="Skip crawl stage (search results only)")
    p.add_argument("--no-research", action="store_true", help="Skip deep research on hot leads")
    p.add_argument("--format", choices=["json", "csv"], default=None, help="Output format override")
    return p.parse_args()


def main() -> int:
    wall_start = time.perf_counter()
    args = _parse_args()

    from common.config import load_config

    cfg = load_config(args.config)

    logging.basicConfig(
        level=getattr(logging, cfg.logging.level, logging.INFO),
        format=cfg.logging.format,
    )
    logger = logging.getLogger("main")

    import common.db as db

    db_url = db.get_database_url()
    if db_url:
        try:
            db.init_engine(db_url)
            logger.info("Database connected: %s", db_url.split("@")[-1])
        except Exception as exc:
            logger.warning("Database unavailable (%s) — continuing without persistence.", exc)

    # CLI overrides
    if args.output:
        cfg.output.save_to = args.output
    if args.top is not None:
        cfg.output.top_leads = args.top
    if args.no_llm_scoring:
        cfg.scoring.llm_enabled = False
    if args.no_crawl:
        cfg.pipeline.crawl_enabled = False
        cfg.pipeline.enrich_enabled = False
    if args.no_research:
        cfg.scoring.research_hot_leads = False
    if args.provider:
        cfg.pipeline.providers = args.provider
    if args.crawler:
        cfg.pipeline.crawler_type = args.crawler
    if args.proxy:
        cfg.proxy.provider = args.proxy
        cfg.proxy.enabled = args.proxy not in ("none", "")
    if args.format:
        cfg.output.format = args.format

    from common.events import EventBus, LoggingObserver, MetricsObserver, ConsoleObserver

    bus = EventBus()
    metrics = MetricsObserver()

    if cfg.events.logging_observer:
        bus.subscribe_all(LoggingObserver())
    if cfg.events.metrics_observer:
        bus.subscribe_all(metrics)
    if cfg.events.console_observer:
        bus.subscribe_all(ConsoleObserver())
    if cfg.events.webhook_enabled and cfg.events.webhook_url:
        from common.events import WebhookObserver
        from common.events.bus import async_handler

        wh = WebhookObserver(
            cfg.events.webhook_url,
            secret_header=cfg.events.webhook_secret or None,
        )
        bus.subscribe_all(wh)

    from common.session import LeadCache, SessionManager, MemoryManager

    cache = LeadCache.from_config(cfg)
    mem = MemoryManager.from_config(cfg)
    sess_mgr = SessionManager.from_config(cfg, cache=cache)

    query = args.query
    if not query:
        query = _prompt_query()
    if not query.strip():
        print("Error: no query provided.", file=sys.stderr)
        return 1

    session = sess_mgr.get_or_create(query, session_id=args.session_id)
    from common.events.events import SessionCreated, SessionResumed

    if session.total_leads == 0:
        bus.publish(SessionCreated(session_id=session.id, query=query))
    else:
        bus.publish(
            SessionResumed(
                session_id=session.id,
                query=query,
                leads_already_found=session.total_leads,
            )
        )

    logger.info("Session: %s (status=%s)", session.id, session.status.value)

    from common.llm import create_llm
    from agents import AgentFactory

    icp_agent = AgentFactory.create("icp_parser", cfg, bus=bus, session=session)
    icp = icp_agent.parse(query)
    logger.info(
        "ICP: industries=%s  tech=%s  titles=%s  [confidence=%.2f]",
        icp.target_company.industries[:3],
        icp.technologies.required[:3],
        icp.buyer_persona.titles[:3],
        icp.confidence,
    )

    proxy_provider = None
    if cfg.proxy.enabled:
        from common.proxy import ProxyProviderFactory

        proxy_provider = ProxyProviderFactory.create(cfg.proxy)
        logger.info("Proxy: %s", cfg.proxy.provider)

    # ── 6. Discovery Pipeline ────────────────────────────────────────────
    from discovery.pipeline import DiscoveryPipeline, PipelineConfig as _PC

    pipe_cfg = _PC(
        providers=cfg.pipeline.providers,
        crawler_type=cfg.pipeline.crawler_type,
        max_results_per_query=cfg.pipeline.max_results_per_query,
        search_workers=cfg.pipeline.search_workers,
        crawl_enabled=cfg.pipeline.crawl_enabled,
        max_urls_to_crawl=cfg.pipeline.max_urls_to_crawl,
        crawl_workers=cfg.pipeline.crawl_workers,
        crawl_timeout=cfg.pipeline.crawl_timeout,
        domain_delay=cfg.pipeline.domain_delay,
        enrich_enabled=cfg.pipeline.enrich_enabled,
        min_lead_score=cfg.pipeline.min_lead_score,
        skip_domains=cfg.pipeline.skip_domains,
        prefer_domains=cfg.pipeline.prefer_domains,
    )

    pipeline = DiscoveryPipeline(
        config=pipe_cfg,
        bus=bus,
        cache=cache,
        proxy_provider=proxy_provider,
        session_id=session.id,
    )

    result = pipeline.run(icp)

    if not result.leads:
        logger.warning("No leads found. Try broadening your query or adding search providers.")
        sess_mgr.mark_completed(session.id, total_leads=0)
        return 0

    # ── 7. Score Leads ───────────────────────────────────────────────────
    top_enriched = result.top_leads(cfg.output.top_leads * 2)

    scorer_agent = AgentFactory.create(
        "lead_scorer",
        cfg,
        bus=bus,
        session=session,
        icp=icp,
        hot_threshold=cfg.scoring.hot_threshold,
        warm_threshold=cfg.scoring.warm_threshold,
        llm_enabled=cfg.scoring.llm_enabled,
    )
    scored = scorer_agent.run(
        enriched_leads=top_enriched,
        max_workers=cfg.scoring.max_concurrent_scorers,
    )
    top_scored = scored[: cfg.output.top_leads]

    # ── 8. Deep Research on HOT leads ───────────────────────────────────
    if cfg.scoring.research_hot_leads:
        hot_leads = [s for s in top_scored if s.lead_tier.value == "hot"]
        if hot_leads:
            logger.info("Deep research on %d hot leads …", len(hot_leads))
            researcher = AgentFactory.create("research", cfg, bus=bus, session=session)
            domain_pages = _group_pages_by_domain(result.crawled_pages)
            for scored_lead in hot_leads[:5]:  # cap at 5 for performance
                pages = domain_pages.get(scored_lead.domain, [])
                if pages:
                    profile = researcher.research(scored_lead.domain, pages)
                    # Merge richer summary back into the scored lead
                    if profile.description and not scored_lead.company_summary:
                        scored_lead.company_summary = profile.description
                    if profile.pitch_angle and not scored_lead.why_this_lead:
                        scored_lead.why_this_lead = profile.pitch_angle
                    # Store in memory manager
                    mem.store_summary(session.id, scored_lead.source_url, profile.description)

    # ── 9. Contact Finding ───────────────────────────────────────────────
    if cfg.scoring.find_contacts:
        logger.info("Finding contacts for top leads …")
        contact_agent = AgentFactory.create("contact_finder", cfg, bus=bus, session=session)
        domain_pages = _group_pages_by_domain(result.crawled_pages)
        for scored_lead in top_scored[:10]:
            pages = domain_pages.get(scored_lead.domain, [])
            if pages and not scored_lead.decision_makers:
                contacts = contact_agent.find_contacts(scored_lead.domain, pages)
                if contacts:
                    scored_lead.decision_makers = contacts

    # ── 10. Update session stats ─────────────────────────────────────────
    tier_counts = Counter(s.lead_tier.value for s in top_scored)
    sess_mgr.mark_completed(
        session.id,
        total_leads=len(top_scored),
        hot_count=tier_counts["hot"],
        warm_count=tier_counts["warm"],
        cold_count=tier_counts["cold"],
        pipeline_ms=result.pipeline_ms,
    )

    # Persist to Postgres via SQLAlchemy ORM
    if db.is_available():
        _persist_results_to_db(session.id, query, top_scored, result)

    # ── 11. Output ───────────────────────────────────────────────────────
    Path(cfg.output.save_to).parent.mkdir(parents=True, exist_ok=True)

    if cfg.output.format == "csv":
        _write_csv(top_scored, cfg.output.save_to)
    else:
        _write_json(top_scored, result, cfg.output.save_to, cfg)

    logger.info("Saved %d leads → %s", len(top_scored), cfg.output.save_to)

    # ── 12. Console summary ──────────────────────────────────────────────
    wall_ms = (time.perf_counter() - wall_start) * 1000
    _print_summary(top_scored, result, wall_ms, session.id, metrics)
    return 0


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _write_json(leads, pipeline_result, path: str, cfg) -> None:
    records = []
    for lead in leads:
        d = lead.to_dict()
        if not cfg.output.include_evidence:
            d.pop("evidence", None)
        records.append(d)
    payload = {
        "query": pipeline_result.icp.original_query,
        "generated_at": pipeline_result.created_at.isoformat(),
        "pipeline_ms": round(pipeline_result.pipeline_ms, 1),
        "total_leads": len(leads),
        "leads": records,
    }
    indent = 2 if cfg.output.pretty_print else None
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=indent, ensure_ascii=False, default=str)


def _write_csv(leads, path: str) -> None:
    fieldnames = [
        "domain",
        "company_name",
        "lead_tier",
        "icp_relevance_score",
        "tech_stack",
        "hiring_signals",
        "outsourcing_signals",
        "company_summary",
        "why_this_lead",
        "emails",
        "linkedin_url",
        "decision_makers",
        "outreach_subject",
        "outreach_hook",
        "source_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for lead in leads:
            w.writerow(
                {
                    "domain": lead.domain,
                    "company_name": lead.company_name,
                    "lead_tier": lead.lead_tier.value,
                    "icp_relevance_score": round(lead.icp_relevance_score, 3),
                    "tech_stack": "; ".join(lead.tech_stack),
                    "hiring_signals": "; ".join(lead.hiring_signals),
                    "outsourcing_signals": "; ".join(lead.outsourcing_signals),
                    "company_summary": lead.company_summary,
                    "why_this_lead": lead.why_this_lead,
                    "emails": "; ".join(lead.contact_info.emails),
                    "linkedin_url": lead.contact_info.linkedin_url or "",
                    "decision_makers": "; ".join(dm.title for dm in lead.decision_makers),
                    "outreach_subject": (
                        lead.outreach_suggestions[0].subject_line
                        if lead.outreach_suggestions
                        else ""
                    ),
                    "outreach_hook": (
                        lead.outreach_suggestions[0].opening_hook
                        if lead.outreach_suggestions
                        else ""
                    ),
                    "source_url": lead.source_url,
                }
            )


def _group_pages_by_domain(pages) -> dict[str, list]:
    groups: dict[str, list] = {}
    for page in pages:
        if page.success:
            groups.setdefault(page.domain, []).append(page)
    return groups


# ---------------------------------------------------------------------------
# Console display
# ---------------------------------------------------------------------------


def _print_summary(leads, pipeline_result, wall_ms, session_id, metrics) -> None:
    tiers = Counter(l.lead_tier.value for l in leads)
    print()
    print("=" * 65)
    print("  AI LEAD GENERATION — COMPLETE")
    print("=" * 65)
    print(f"  Session    : {session_id}")
    print(f"  Total leads: {len(leads)}")
    print(f"  🔥 Hot     : {tiers['hot']}")
    print(f"  🌤  Warm    : {tiers['warm']}")
    print(f"  ❄️  Cold    : {tiers['cold']}")
    print(f"  Total time : {wall_ms / 1000:.1f}s")
    m = metrics.snapshot()
    print(
        f"  Crawled    : {m.get('crawl_attempts', 0)} pages  "
        f"({m.get('crawl_from_cache', 0)} from cache)"
    )
    print(
        f"  Search     : {m.get('search_results', 0)} results across "
        f"{m.get('search_calls', 0)} provider calls"
    )
    print("=" * 65)

    hot_warm = [l for l in leads if l.lead_tier.value in ("hot", "warm")]
    if hot_warm:
        print(f"\n  Top {min(10, len(hot_warm))} leads:\n")
        for i, lead in enumerate(hot_warm[:10], 1):
            icon = "🔥" if lead.lead_tier.value == "hot" else "🌤 "
            techs = ", ".join(lead.tech_stack[:4]) or "—"
            summary = (lead.company_summary or "")[:70]
            print(f"  {i:>2}. {icon}[{lead.icp_relevance_score:.2f}] {lead.company_name}")
            print(f"      {lead.domain}")
            print(f"      Tech: {techs}")
            if summary:
                print(f"      {summary}")
            if lead.outreach_suggestions:
                s = lead.outreach_suggestions[0]
                if s.subject_line:
                    print(f"      → {s.subject_line}")
            if lead.decision_makers:
                dm_list = ", ".join(dm.title for dm in lead.decision_makers[:2])
                print(f"      Contacts: {dm_list}")
            print()

    print(f"  Output: {pipeline_result.icp.original_query[:50]}")
    print("=" * 65)


def _persist_results_to_db(session_id: str, query: str, scored_leads, pipeline_result) -> None:
    import common.db as db
    from common.db.repositories import (
        SessionRepository, LeadRepository, CompanyRepository,
        DecisionMakerRepository, PipelineMetricRepository,
    )
    from collections import Counter

    tiers = Counter(s.lead_tier.value for s in scored_leads)
    try:
        with db.db_session() as orm_db:
            sess_repo = SessionRepository(orm_db)
            sess_repo.upsert_or_create(session_id, query, tiers)

            lead_repo = LeadRepository(orm_db)
            company_repo = CompanyRepository(orm_db)
            dm_repo = DecisionMakerRepository(orm_db)

            for lead in scored_leads:
                company_repo.upsert(
                    domain=lead.domain,
                    company_name=lead.company_name,
                    tech_stack=lead.tech_stack,
                    industry_tags=lead.industry_signals,
                    linkedin_url=lead.contact_info.linkedin_url,
                    github_url=lead.contact_info.github_url,
                    twitter_url=lead.contact_info.twitter_url,
                    crunchbase_url=lead.contact_info.crunchbase_url,
                    website=lead.source_url,
                )
                lead_record = lead_repo.upsert(
                    session_id=session_id,
                    domain=lead.domain,
                    company_name=lead.company_name,
                    lead_tier=lead.lead_tier.value,
                    icp_relevance_score=lead.icp_relevance_score,
                    tech_score=lead.score_breakdown.technology,
                    hiring_score=lead.score_breakdown.hiring,
                    profile_score=lead.score_breakdown.profile,
                    tech_stack=lead.tech_stack,
                    hiring_signals=lead.hiring_signals,
                    outsourcing_signals=lead.outsourcing_signals,
                    business_events=lead.business_events,
                    industry_signals=lead.industry_signals,
                    company_summary=lead.company_summary,
                    why_this_lead=lead.why_this_lead,
                    source_url=lead.source_url,
                    evidence=lead.evidence,
                )
                for dm in lead.decision_makers:
                    try:
                        dm_repo.upsert(
                            domain=lead.domain,
                            title=dm.title,
                            full_name=dm.name,
                            email=dm.email,
                            linkedin_url=dm.linkedin_url,
                            confidence=dm.confidence,
                            session_id=session_id,
                        )
                    except Exception:
                        pass

            for metric in pipeline_result.stage_metrics:
                PipelineMetricRepository(orm_db).log_stage(
                    session_id=session_id,
                    stage=metric.stage,
                    items_in=metric.items_in,
                    items_out=metric.items_out,
                    error_count=metric.error_count,
                    latency_ms=metric.latency_ms,
                )

            orm_db.commit()
    except Exception as exc:
        import logging
        logging.getLogger("main").warning("DB persist error: %s", exc)


def _prompt_query() -> str:
    print("AI Lead Generation Agent")
    print("-" * 45)
    print("Example: 'US B2B SaaS 50-500 employees Kubernetes, hiring")
    print("          backend engineers, recently funded, target CTOs'")
    print()
    try:
        return input("Enter ICP query: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


if __name__ == "__main__":
    sys.exit(main())
