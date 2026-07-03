from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common.events.bus import EventBus

logger = logging.getLogger(__name__)


def run_pipeline(
    query: str,
    session_id: str,
    config_overrides: dict | None = None,
    bus: "EventBus | None" = None,
) -> dict:
    """Execute a full lead generation pipeline run.

    Can be called directly (CLI, BackgroundTasks, SSE thread) or dispatched
    as a Celery task. Returns a summary dict of the run.

    Args:
        bus: Pre-configured EventBus (e.g. carrying an SseObserver). When
             None a default bus with LoggingObserver is created.
    """
    from common.config import load_config
    from common.events import EventBus, LoggingObserver
    from common.session import LeadCache
    from common.ratelimit import RateLimiterRegistry
    from services import PipelineService, PersistenceService

    cfg = load_config()
    RateLimiterRegistry.configure(cfg.rate_limits.to_dict())

    overrides = config_overrides or {}
    if overrides.get("providers"):
        cfg.pipeline.providers = overrides["providers"]
    if overrides.get("max_leads"):
        cfg.output.top_leads = int(overrides["max_leads"])
    if overrides.get("no_crawl"):
        cfg.pipeline.crawl_enabled = False
    if overrides.get("no_llm_scoring"):
        cfg.scoring.llm_enabled = False
    if overrides.get("crawler"):
        cfg.pipeline.crawler_type = overrides["crawler"]

    if bus is None:
        bus = EventBus()
        bus.subscribe_all(LoggingObserver())

    if overrides.get("webhook_url"):
        from common.events import WebhookObserver

        bus.subscribe_all(WebhookObserver(overrides["webhook_url"]))

    cache = LeadCache.from_config(cfg)
    svc = PipelineService(cfg, bus=bus, cache=cache)
    run = svc.run(query, session_id=session_id)
    PersistenceService().save(run)

    return {
        "session_id": run.session_id,
        "total_leads": len(run.scored_leads),
        "tier_counts": run.tier_counts,
        "wall_ms": round(run.wall_ms, 1),
    }


# ---------------------------------------------------------------------------
# Celery task registration (optional — graceful if celery not installed)
# ---------------------------------------------------------------------------

run_pipeline_task = None

try:
    from tasks.celery_app import celery_app

    if celery_app is not None:

        @celery_app.task(
            bind=True,
            name="tasks.pipeline_task.run_pipeline",
            max_retries=2,
            default_retry_delay=30,
        )
        def run_pipeline_task(
            self, query: str, session_id: str, config_overrides: dict | None = None
        ):
            try:
                return run_pipeline(query, session_id, config_overrides)
            except Exception as exc:
                logger.error("Pipeline task %s failed: %s", session_id, exc)
                raise self.retry(exc=exc, countdown=30)

except Exception:
    pass
