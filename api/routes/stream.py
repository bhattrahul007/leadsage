from __future__ import annotations

import logging
import threading
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.schemas import RunRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/runs/stream",
    summary="Submit a run and stream live pipeline events (SSE)",
    response_class=StreamingResponse,
)
async def stream_run(req: RunRequest) -> StreamingResponse:
    """Run the pipeline and stream every step as Server-Sent Events.

    The client receives a continuous stream of JSON lines::

        data: {"type": "PipelineStarted",  "data": {...}}
        data: {"type": "SearchCompleted",  "data": {...}}
        data: {"type": "CrawlCompleted",   "data": {...}}
        data: {"type": "IcpParsed",        "data": {...}}
        data: {"type": "LeadScored",       "data": {...}}
        data: {"type": "ContextCompressed","data": {...}}
        data: {"type": "LlmCacheHit",      "data": {...}}
        ...
        data: {"type": "done"}

    The ``X-Session-Id`` response header carries the session ID for follow-up
    polling via ``GET /runs/{session_id}/status``.
    """
    from fastapi import HTTPException

    from common.events import EventBus, LoggingObserver, SseObserver
    from common.sanitise import sanitise_query

    try:
        query = sanitise_query(req.query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    session_id = str(uuid.uuid4())

    bus = EventBus()
    bus.subscribe_all(LoggingObserver())
    sse = SseObserver(session_id)
    bus.subscribe_all(sse)

    overrides = {
        "providers": req.providers or [],
        "max_leads": req.max_leads,
        "crawler": req.crawler,
        "no_crawl": req.no_crawl,
        "no_llm_scoring": req.no_llm_scoring,
        "webhook_url": req.webhook_url or "",
    }

    def _run() -> None:
        try:
            from tasks.pipeline_task import run_pipeline

            run_pipeline(query, session_id, overrides, bus=bus)
        except Exception as exc:
            logger.error("SSE run %s failed: %s", session_id, exc)
        finally:
            sse.close()

    threading.Thread(target=_run, daemon=True, name=f"sse-{session_id[:8]}").start()

    return StreamingResponse(
        sse.stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session_id,
        },
    )
