from __future__ import annotations

import concurrent.futures
import logging
import threading
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

Handler = Callable[[Any], None]


def async_handler(fn: Handler, executor: concurrent.futures.Executor | None = None) -> Handler:
    """
    Wraps ``fn`` so it runs in a thread pool (fire-and-forget).

    Use this for slow observers (webhooks, DB writes) so they never block
    the main pipeline thread.

    Args:
        fn:       The observer callback.
        executor: Optional shared ``ThreadPoolExecutor``. Defaults to
                  a new daemon executor.
    """
    _exec = executor or concurrent.futures.ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix=f"async_obs_{fn.__name__}",
    )

    def _wrapper(event: Any) -> None:
        _exec.submit(fn, event)

    _wrapper.__name__ = f"async_{fn.__name__}"
    return _wrapper


class EventBus:
    """
    Central, thread-safe publish/subscribe event dispatcher.

    Attributes
    ----------
    _subscribers:
        ``{event_type: [handler, ...]}`` mapping.
    _lock:
        Guards subscriber mutations (not needed for reads in CPython
        but kept for correctness on all interpreters).
    """

    def __init__(self) -> None:
        self._subscribers: dict[type, list[Handler]] = defaultdict(list)
        self._lock = threading.RLock()
        self._publish_count: int = 0
        self._error_count: int = 0

    def subscribe(self, event_type: type, handler: Handler) -> None:
        """
        Register ``handler`` to be called whenever ``event_type`` is published.

        Args:
            event_type: The event class (e.g. ``CrawlCompleted``).
            handler:    Callable that accepts a single event argument.
        """
        with self._lock:
            self._subscribers[event_type].append(handler)
            logger.debug(
                "[EventBus] subscribed %s → %s",
                event_type.__name__,
                getattr(handler, "__name__", repr(handler)),
            )

    def subscribe_all(self, observer: "BaseObserver") -> None:
        """
        Register an observer for all event types it declares interest in.

        Calls ``observer.subscribes_to()`` and registers ``observer.handle``
        for each returned type.
        """
        for event_type in observer.subscribes_to():
            self.subscribe(event_type, observer.handle)

    def unsubscribe(self, event_type: type, handler: Handler) -> None:
        """Remove a previously registered handler."""
        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            try:
                handlers.remove(handler)
            except ValueError:
                pass

    def publish(self, event: Any) -> None:
        """
        Dispatch ``event`` to all registered handlers for its type.

        Exceptions from handlers are caught, logged, and the bus continues
        dispatching to remaining handlers. The publisher never sees errors.

        Args:
            event: Any dataclass event instance from ``common.events.events``.
        """
        handlers = self._subscribers.get(type(event), [])
        self._publish_count += 1

        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                self._error_count += 1
                logger.exception(
                    "[EventBus] handler %s raised on event %s: %s",
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
        """Clear all subscriptions and counters. Useful for testing."""
        with self._lock:
            self._subscribers.clear()
            self._publish_count = 0
            self._error_count = 0


_default_bus: EventBus | None = None


def get_default_bus() -> EventBus:
    """Return (lazily creating) the process-wide default ``EventBus``."""
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus
