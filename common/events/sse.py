from collections.abc import AsyncGenerator
import dataclasses
import json
import queue
from typing import Any

from common.events.events import ALL_EVENT_TYPES
from common.events.observers import BaseObserver

_SENTINEL = object()


class SseObserver(BaseObserver):
    """Bridges sync EventBus events into an async SSE generator.

    Thread-safe: pipeline thread calls handle(); HTTP handler awaits stream().
    Events not matching session_id are silently dropped.
    """

    def __init__(self, session_id: str, maxsize: int = 512) -> None:
        self._sid = session_id
        self._q: queue.Queue[Any] = queue.Queue(maxsize=maxsize)

    def subscribes_to(self) -> list[type]:
        return list(ALL_EVENT_TYPES)

    def handle(self, event: Any) -> None:
        if hasattr(event, "session_id") and event.session_id != self._sid:
            return
        try:
            self._q.put_nowait(event)
        except queue.Full:
            pass  # drop oldest-first if client is too slow

    def close(self) -> None:
        """Signal end-of-stream to the async generator."""
        try:
            self._q.put_nowait(_SENTINEL)
        except queue.Full:
            pass

    async def stream(self) -> AsyncGenerator[str, None]:
        """Async generator that yields SSE-formatted strings until close() is called."""
        import asyncio

        loop = asyncio.get_event_loop()
        while True:
            event = await loop.run_in_executor(None, self._q.get)
            if event is _SENTINEL:
                yield 'data: {"type":"done"}\n\n'
                break
            yield _to_sse(event)


def _to_sse(event: Any) -> str:
    """Serialize a pipeline event to an SSE data line."""
    # is_dataclass returns True for both instances AND classes; guard with isinstance
    if dataclasses.is_dataclass(event) and not isinstance(event, type):
        d: dict[str, Any] = dataclasses.asdict(event)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
    else:
        d = {"repr": repr(event)}
    payload = {"type": type(event).__name__, "data": d}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
