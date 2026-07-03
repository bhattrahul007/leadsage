from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
import concurrent.futures
import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from common.events.observers import BaseObserver

logger = logging.getLogger(__name__)

Handler = Callable[[Any], None]


def async_handler(fn: Handler, executor: concurrent.futures.Executor | None = None) -> Handler:
    """Wrap fn so it runs in a thread pool (fire-and-forget)."""
    _exec = executor or concurrent.futures.ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix=f"async_obs_{fn.__name__}",
    )

    def _wrapper(event: Any) -> None:
        _exec.submit(fn, event)

    _wrapper.__name__ = f"async_{fn.__name__}"
    return _wrapper


class EventBus:
    """Thread-safe publish/subscribe dispatcher."""

    def __init__(self) -> None:
        self._subscribers: dict[type, list[Handler]] = defaultdict(list)
        self._lock = threading.RLock()
        self._publish_count: int = 0
        self._error_count: int = 0

    def subscribe(self, event_type: type, handler: Handler) -> None:
        with self._lock:
            self._subscribers[event_type].append(handler)
            logger.debug(
                "[EventBus] subscribed %s → %s",
                event_type.__name__,
                getattr(handler, "__name__", repr(handler)),
            )

    def subscribe_all(self, observer: BaseObserver) -> None:
        """Register an observer for all event types it declares."""
        for event_type in observer.subscribes_to():
            self.subscribe(event_type, observer.handle)

    def unsubscribe(self, event_type: type, handler: Handler) -> None:
        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            try:
                handlers.remove(handler)
            except ValueError:
                pass

    def publish(self, event: Any) -> None:
        """Dispatch event to all registered handlers. Exceptions are caught per-handler."""
        handlers = self._subscribers.get(type(event), [])
        self._publish_count += 1
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                self._error_count += 1
                logger.exception(
                    "[EventBus] handler %s raised on %s: %s",
                    getattr(handler, "__name__", repr(handler)),
                    type(event).__name__,
                    exc,
                )

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "subscriptions": {k.__name__: len(v) for k, v in self._subscribers.items()},
                "publish_count": self._publish_count,
                "error_count": self._error_count,
            }

    def reset(self) -> None:
        """Clear all subscriptions and counters."""
        with self._lock:
            self._subscribers.clear()
            self._publish_count = 0
            self._error_count = 0


_default_bus: EventBus | None = None


def get_default_bus() -> EventBus:
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus
