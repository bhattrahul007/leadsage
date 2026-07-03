from __future__ import annotations

import argparse
import csv
import json
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
    p.add_argument("--config", "-c", default=None, metavar="PATH")
    p.add_argument("--output", "-o", default=None, metavar="PATH")
    p.add_argument("--top", "-n", type=int, default=None)
    p.add_argument("--session-id", default=None, metavar="ID")
    p.add_argument("--proxy", default=None, metavar="PROVIDER")
    p.add_argument("--crawler", default=None)
    p.add_argument("--provider", metavar="NAME", action="append", default=None)
    p.add_argument("--no-llm-scoring", action="store_true")
    p.add_argument("--no-crawl", action="store_true")
    p.add_argument("--no-research", action="store_true")
    p.add_argument("--format", choices=["json", "csv"], default=None)
    return p.parse_args()


def main() -> int:
    wall_start = time.perf_counter()
    args = _parse_args()

    from common.config import load_config

    cfg = load_config(args.config)

    from common import logging_config

    logging_config.configure(
        level=cfg.logging.level,
        json_format=cfg.logging.json_format,
        fmt=cfg.logging.format,
    )
    import logging

    logger = logging.getLogger("main")

    # DB init
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

    # Rate limiter bootstrap
    from common.ratelimit import RateLimiterRegistry

    RateLimiterRegistry.configure(cfg.rate_limits.to_dict())

    # Event bus
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

        bus.subscribe_all(
            WebhookObserver(cfg.events.webhook_url, secret_header=cfg.events.webhook_secret or None)
        )

    # Cache
    from common.session import LeadCache

    cache = LeadCache.from_config(cfg)

    query = args.query or _prompt_query()
    if not query.strip():
        print("Error: no query provided.", file=sys.stderr)
        return 1

    from common.sanitise import sanitise_query

    try:
        query = sanitise_query(query)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    from services import PipelineService, PersistenceService

    svc = PipelineService(cfg, bus=bus, cache=cache)
    run = svc.run(query, session_id=args.session_id)

    if not run.scored_leads:
        logger.warning("No leads found. Try broadening your query or adding search providers.")
        return 0

    PersistenceService().save(run)
    Path(cfg.output.save_to).parent.mkdir(parents=True, exist_ok=True)
    if cfg.output.format == "csv":
        _write_csv(run.scored_leads, cfg.output.save_to)
    else:
        _write_json(run.scored_leads, run.pipeline_result, cfg.output.save_to, cfg)

    logger.info("Saved %d leads → %s", len(run.scored_leads), cfg.output.save_to)

    wall_ms = (time.perf_counter() - wall_start) * 1000
    _print_summary(run.scored_leads, run.pipeline_result, wall_ms, run.session_id, metrics)
    return 0


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
