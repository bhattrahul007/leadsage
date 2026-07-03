from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Any

from common.context.window import SummaryBufferWindow

if TYPE_CHECKING:
    from common.config import AppConfig
    from common.events.bus import EventBus
    from common.session.cache import LeadCache

logger = logging.getLogger(__name__)

_WINDOWS: dict[str, SummaryBufferWindow] = {}


def get_window(
    session_id: str,
    config: "AppConfig",
    cache: "LeadCache | None" = None,
    bus: "EventBus | None" = None,
) -> SummaryBufferWindow:
    """Return (or create) the SummaryBufferWindow for a session.

    Singleton per session_id within the process. Redis-backed so state
    survives across API requests. If a bus is provided, context compression
    events will be published to it.
    """
    if session_id in _WINDOWS:
        win = _WINDOWS[session_id]
        if bus and win._emit is None:
            win._emit = bus.publish
        return win

    redis = None
    if cache and cache._redis and cache._redis.available:
        redis = cache._redis

    emit_fn: Callable[[Any], None] | None = bus.publish if bus else None

    window = SummaryBufferWindow(
        session_id=session_id,
        max_tokens=config.session.context_max_tokens,
        max_turns=config.session.context_max_turns,
        chunk_size=config.session.context_chunk_size,
        redis_backend=redis,
        emit_fn=emit_fn,
    )
    _WINDOWS[session_id] = window
    return window


def flush_window(session_id: str) -> None:
    """Remove a session window from the process cache."""
    _WINDOWS.pop(session_id, None)
