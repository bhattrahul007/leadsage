from abc import ABC, abstractmethod
from collections import defaultdict
import logging
import threading
from typing import Any

from common.events.events import (
    ALL_EVENT_TYPES,
    CrawlCompleted,
    CrawlFailed,
    IcpParsed,
    LeadEnriched,
    LeadScored,
    PipelineCompleted,
    PipelineFailed,
    PipelineStarted,
    ProxyFailed,
    ProxyRotated,
    QueryPlanned,
    SearchCompleted,
    SessionCreated,
    SessionResumed,
)

logger = logging.getLogger(__name__)


class BaseObserver(ABC):
    """Abstract observer — subscribe to EventBus events.

    Implement ``subscribes_to()`` (which event types) and ``handle(event)``
    (the callback). Never raise inside handle — catch errors internally.
    """

    @abstractmethod
    def subscribes_to(self) -> list[type]: ...

    @abstractmethod
    def handle(self, event: Any) -> None: ...


class LoggingObserver(BaseObserver):
    """Writes one structured log line per event (INFO for key events, DEBUG otherwise)."""

    _INFO_TYPES: frozenset[type] = frozenset(
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
        return list(ALL_EVENT_TYPES)

    def handle(self, event: Any) -> None:
        level = logging.INFO if type(event) in self._INFO_TYPES else logging.DEBUG
        logger.log(level, "[event] %s %s", type(event).__name__, _event_summary(event))


class MetricsObserver(BaseObserver):
    """Accumulates pipeline metrics in-memory. Read via ``snapshot()``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = defaultdict(int)
        self._totals: dict[str, float] = defaultdict(float)

    def subscribes_to(self) -> list[type]:
        return [
            SearchCompleted,
            CrawlCompleted,
            CrawlFailed,
            LeadEnriched,
            LeadScored,
            ProxyRotated,
            ProxyFailed,
            PipelineCompleted,
        ]

    def handle(self, event: Any) -> None:
        with self._lock:
            t = type(event)
            if t is SearchCompleted:
                self._counts["search_calls"] += 1
                self._counts["search_results"] += event.result_count
                self._totals["search_latency_ms"] += event.latency_ms
            elif t is CrawlCompleted:
                self._counts["crawl_attempts"] += 1
                if event.success:
                    self._counts["crawl_successes"] += 1
                if event.from_cache:
                    self._counts["crawl_from_cache"] += 1
                self._totals["crawl_latency_ms"] += event.latency_ms
            elif t is CrawlFailed:
                self._counts["crawl_failures"] += 1
            elif t is LeadEnriched:
                self._counts["leads_enriched"] += 1
            elif t is LeadScored:
                self._counts["leads_scored"] += 1
                self._counts[f"leads_{event.tier}"] += 1
            elif t is ProxyRotated:
                self._counts["proxy_rotations"] += 1
            elif t is ProxyFailed:
                self._counts["proxy_failures"] += 1
            elif t is PipelineCompleted:
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
                    c.get("crawl_successes", 0) / max(c.get("crawl_attempts", 1), 1), 3
                ),
            }

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._totals.clear()


class ConsoleObserver(BaseObserver):
    """Prints concise progress lines to stdout (CLI use)."""

    _TIER_ICON = {"hot": "🔥", "warm": "🌤 ", "cold": "❄️ "}

    def subscribes_to(self) -> list[type]:
        return [
            PipelineStarted,
            PipelineCompleted,
            CrawlCompleted,
            LeadScored,
            SearchCompleted,
            ProxyRotated,
        ]

    def handle(self, event: Any) -> None:
        t = type(event)
        if t is PipelineStarted:
            print(f"\n🚀 Pipeline started — query: {event.query[:70]}")
        elif t is SearchCompleted:
            status = "✓" if event.success else "✗"
            print(
                f"  {status}  [search]  {event.provider:10s}  {event.result_count} results  ({event.latency_ms:.0f}ms)"
            )
        elif t is CrawlCompleted:
            status = "✓" if event.success else "✗"
            cached = " [cache]" if event.from_cache else ""
            print(
                f"  {status}  [crawl]   {_truncate(event.url, 60)}{cached}  ({event.latency_ms:.0f}ms)"
            )
        elif t is LeadScored:
            icon = self._TIER_ICON.get(event.tier, "")
            print(
                f"  {icon} [lead]    {event.company_name:30s}  score={event.icp_score:.2f}  {event.tier.upper()}"
            )
        elif t is ProxyRotated:
            print(f"  ↻  [proxy]  rotated → {event.new_proxy}  ({event.reason})")
        elif t is PipelineCompleted:
            print(
                f"\n✅ Pipeline done  {event.total_leads} leads  "
                f"🔥{event.hot_count} / 🌤{event.warm_count} / ❄️{event.cold_count}  "
                f"({event.pipeline_ms / 1000:.1f}s)\n"
            )


class WebhookObserver(BaseObserver):
    """POSTs every event as JSON to a webhook URL (fire-and-forget thread pool)."""

    def __init__(
        self,
        url: str,
        event_types: list[type] | None = None,
        secret_header: str | None = None,
        timeout: int = 5,
    ) -> None:
        import concurrent.futures

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

            payload = {"event_type": type(event).__name__, "data": _event_to_dict(event)}
            requests.post(self._url, json=payload, headers=self._headers, timeout=self._timeout)
        except Exception as exc:
            logger.debug("WebhookObserver send failed: %s", exc)


def _event_summary(event: Any) -> str:
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
    import dataclasses

    if dataclasses.is_dataclass(event):
        d = dataclasses.asdict(event)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        return d
    return {"repr": repr(event)}


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"
