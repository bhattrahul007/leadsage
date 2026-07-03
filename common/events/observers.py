from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class BaseObserver(ABC):
    """
    Abstract observer. Subclass this to create custom observers.

    Implement:
    - ``subscribes_to()`` → the event types this observer cares about
    - ``handle(event)``   → the handler called by the EventBus

    Example::

        class SlackObserver(BaseObserver):
            def subscribes_to(self):
                return [PipelineCompleted, LeadScored]

            def handle(self, event):
                if isinstance(event, PipelineCompleted):
                    slack.send(f"Pipeline done: {event.total_leads} leads")
    """

    @abstractmethod
    def subscribes_to(self) -> list[type]:
        """Return the list of event types this observer handles."""
        ...

    @abstractmethod
    def handle(self, event: Any) -> None:
        """Process one event. Never raise — catch errors internally."""
        ...


class LoggingObserver(BaseObserver):
    """
    Writes one structured log line per event.

    The log level is configurable (default INFO for key events, DEBUG for
    fine-grained events like individual crawl requests).
    """

    from common.events.events import (
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
    )

    _INFO_TYPES = frozenset(
        [
            PipelineStarted,
            PipelineCompleted,
            PipelineFailed,
            IcpParsed,
            QueryPlanned,
            LeadScored,
            LeadEnriched,
            SessionCreated,
            SessionResumed,
            ProxyFailed,
            ProxyRotated,
        ]
    )

    def subscribes_to(self) -> list[type]:
        from common.events.events import ALL_EVENT_TYPES

        return list(ALL_EVENT_TYPES)

    def handle(self, event: Any) -> None:
        level = logging.INFO if type(event) in self._INFO_TYPES else logging.DEBUG
        logger.log(level, "[event] %s %s", type(event).__name__, _event_summary(event))


class MetricsObserver(BaseObserver):
    """
    Accumulates pipeline metrics in-memory.

    Access via ``observer.snapshot()`` for a JSON-safe dict.

    Tracked::

        search_calls:     total provider calls
        search_results:   total results returned
        crawl_attempts:   total URLs crawled
        crawl_successes:  successful crawls
        crawl_from_cache: cache-hit crawls
        leads_enriched:   passed min_score
        leads_hot:        hot tier count
        leads_warm:       warm tier count
        leads_cold:       cold tier count
        proxy_rotations:  proxy rotation count
        proxy_failures:   proxy failure count
        pipeline_runs:    total complete pipeline runs
        avg_pipeline_ms:  rolling average pipeline time
    """

    from common.events.events import (
        SearchCompleted,
        CrawlCompleted,
        CrawlFailed,
        LeadEnriched,
        LeadScored,
        ProxyRotated,
        ProxyFailed,
        PipelineCompleted,
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = defaultdict(int)
        self._totals: dict[str, float] = defaultdict(float)

    def subscribes_to(self) -> list[type]:
        return [
            self.SearchCompleted,
            self.CrawlCompleted,
            self.CrawlFailed,
            self.LeadEnriched,
            self.LeadScored,
            self.ProxyRotated,
            self.ProxyFailed,
            self.PipelineCompleted,
        ]

    def handle(self, event: Any) -> None:
        with self._lock:
            t = type(event)
            if t is self.SearchCompleted:
                self._counts["search_calls"] += 1
                self._counts["search_results"] += event.result_count
                self._totals["search_latency_ms"] += event.latency_ms

            elif t is self.CrawlCompleted:
                self._counts["crawl_attempts"] += 1
                if event.success:
                    self._counts["crawl_successes"] += 1
                if event.from_cache:
                    self._counts["crawl_from_cache"] += 1
                self._totals["crawl_latency_ms"] += event.latency_ms

            elif t is self.CrawlFailed:
                self._counts["crawl_failures"] += 1

            elif t is self.LeadEnriched:
                self._counts["leads_enriched"] += 1

            elif t is self.LeadScored:
                self._counts["leads_scored"] += 1
                self._counts[f"leads_{event.tier}"] += 1

            elif t is self.ProxyRotated:
                self._counts["proxy_rotations"] += 1

            elif t is self.ProxyFailed:
                self._counts["proxy_failures"] += 1

            elif t is self.PipelineCompleted:
                self._counts["pipeline_runs"] += 1
                self._totals["pipeline_ms"] += event.pipeline_ms

    def snapshot(self) -> dict:
        """Return a JSON-safe snapshot of all metrics."""
        with self._lock:
            c = dict(self._counts)
            runs = c.get("pipeline_runs", 0)
            avg_ms = self._totals["pipeline_ms"] / runs if runs > 0 else 0.0
            return {
                **c,
                "avg_pipeline_ms": round(avg_ms, 1),
                "crawl_success_rate": round(
                    c.get("crawl_successes", 0) / max(c.get("crawl_attempts", 1), 1),
                    3,
                ),
            }

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._totals.clear()


class ConsoleObserver(BaseObserver):
    """
    Prints concise progress lines to stdout. Good for CLI use.

    Format::

        ✓  [crawl]  https://acmecorp.com  (123ms)
        🔥 [lead]   acmecorp.com  score=0.82  HOT
    """

    from common.events.events import (
        PipelineStarted,
        PipelineCompleted,
        CrawlCompleted,
        LeadScored,
        SearchCompleted,
        ProxyRotated,
    )

    _TIER_ICON = {"hot": "🔥", "warm": "🌤 ", "cold": "❄️ "}

    def subscribes_to(self) -> list[type]:
        return [
            self.PipelineStarted,
            self.PipelineCompleted,
            self.CrawlCompleted,
            self.LeadScored,
            self.SearchCompleted,
            self.ProxyRotated,
        ]

    def handle(self, event: Any) -> None:
        t = type(event)
        if t is self.PipelineStarted:
            print(f"\n🚀 Pipeline started — query: {event.query[:70]}")
        elif t is self.SearchCompleted:
            status = "✓" if event.success else "✗"
            print(
                f"  {status}  [search]  {event.provider:10s}  {event.result_count} results  ({event.latency_ms:.0f}ms)"
            )
        elif t is self.CrawlCompleted:
            status = "✓" if event.success else "✗"
            cached = " [cache]" if event.from_cache else ""
            print(
                f"  {status}  [crawl]   {_truncate(event.url, 60)}{cached}  ({event.latency_ms:.0f}ms)"
            )
        elif t is self.LeadScored:
            icon = self._TIER_ICON.get(event.tier, "")
            print(
                f"  {icon} [lead]    {event.company_name:30s}  score={event.icp_score:.2f}  {event.tier.upper()}"
            )
        elif t is self.ProxyRotated:
            print(f"  ↻  [proxy]  rotated → {event.new_proxy}  ({event.reason})")
        elif t is self.PipelineCompleted:
            print(
                f"\n✅ Pipeline done  {event.total_leads} leads  "
                f"🔥{event.hot_count} / 🌤{event.warm_count} / ❄️{event.cold_count}  "
                f"({event.pipeline_ms / 1000:.1f}s)\n"
            )


class WebhookObserver(BaseObserver):
    """
    POSTs every event as JSON to a configured webhook URL.

    Runs in a background thread so it never blocks the pipeline.

    Args:
        url:           Webhook endpoint.
        event_types:   Subset of event types to forward (default: all).
        secret_header: Optional ``Authorization`` header value.
        timeout:       HTTP timeout in seconds.
    """

    def __init__(
        self,
        url: str,
        event_types: list[type] | None = None,
        secret_header: str | None = None,
        timeout: int = 5,
    ) -> None:
        import concurrent.futures
        from common.events.events import ALL_EVENT_TYPES

        self._url = url
        self._types = event_types or list(ALL_EVENT_TYPES)
        self._headers = {"Content-Type": "application/json"}
        if secret_header:
            self._headers["Authorization"] = secret_header
        self._timeout = timeout
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="webhook_obs"
        )

    def subscribes_to(self) -> list[type]:
        return self._types

    def handle(self, event: Any) -> None:
        self._pool.submit(self._send, event)

    def _send(self, event: Any) -> None:
        try:
            import requests

            payload = {
                "event_type": type(event).__name__,
                "data": _event_to_dict(event),
            }
            requests.post(
                self._url,
                json=payload,
                headers=self._headers,
                timeout=self._timeout,
            )
        except Exception as exc:
            logger.debug("WebhookObserver send failed: %s", exc)


def _event_summary(event: Any) -> str:
    """Short human-readable summary of an event for log lines."""
    fields = []
    for k, v in vars(event).items():
        if k == "timestamp":
            continue
        s = str(v)
        fields.append(f"{k}={s[:40]!r}" if len(s) > 40 else f"{k}={v!r}")
        if len(fields) >= 5:
            break
    return "{" + ", ".join(fields) + "}"


def _event_to_dict(event: Any) -> dict:
    """Convert a frozen dataclass event to a JSON-safe dict."""
    import dataclasses

    if dataclasses.is_dataclass(event):
        d = dataclasses.asdict(event)
        # datetime → ISO string
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        return d
    return {"repr": repr(event)}


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"
