from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from common.events.observers import BaseObserver

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _get_metrics():
    """Lazy import to avoid hard dependency on prometheus_client."""
    try:
        from prometheus_client import Counter, Gauge, Histogram

        return Counter, Histogram, Gauge
    except ImportError:
        return None, None, None


Counter, Histogram, Gauge = _get_metrics()

if Counter is not None:
    LEADS_FOUND = Counter("prospector_leads_total", "Total leads found by tier", ["tier"])
    CRAWL_LATENCY = Histogram("prospector_crawl_latency_seconds", "Page crawl latency in seconds")
    SEARCH_LATENCY = Histogram(
        "prospector_search_latency_seconds",
        "Search provider latency in seconds",
        ["provider"],
    )
    PIPELINE_RUNS = Counter("prospector_pipeline_runs_total", "Completed pipeline runs")
    CACHE_HITS = Counter("prospector_cache_hits_total", "Cache hits by cache_type", ["cache_type"])
else:
    LEADS_FOUND = CRAWL_LATENCY = SEARCH_LATENCY = PIPELINE_RUNS = CACHE_HITS = None


class PrometheusObserver(BaseObserver):
    """
    Exports pipeline metrics to Prometheus.

    Requires ``prometheus_client`` to be installed::

        uv pip install prometheus-client

    Start the metrics HTTP server before attaching::

        from prometheus_client import start_http_server
        start_http_server(9090)
        bus.subscribe_all(PrometheusObserver())
    """

    def subscribes_to(self) -> list[type]:
        from common.events.events import (
            CacheHit,
            CrawlCompleted,
            LeadScored,
            PipelineCompleted,
            SearchCompleted,
        )

        return [LeadScored, CrawlCompleted, SearchCompleted, PipelineCompleted, CacheHit]

    def handle(self, event: Any) -> None:
        if Counter is None:
            return  # prometheus_client not installed
        from common.events.events import (
            CacheHit,
            CrawlCompleted,
            LeadScored,
            PipelineCompleted,
            SearchCompleted,
        )

        t = type(event)
        try:
            if t is LeadScored:
                LEADS_FOUND.labels(tier=event.tier).inc()
            elif t is CrawlCompleted and not event.from_cache:
                CRAWL_LATENCY.observe(event.latency_ms / 1000)
            elif t is SearchCompleted:
                SEARCH_LATENCY.labels(provider=event.provider).observe(event.latency_ms / 1000)
            elif t is PipelineCompleted:
                PIPELINE_RUNS.inc()
            elif t is CacheHit:
                CACHE_HITS.labels(cache_type=event.cache_type).inc()
        except Exception as exc:
            logger.debug("PrometheusObserver error: %s", exc)
