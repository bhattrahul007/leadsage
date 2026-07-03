import logging
import uuid
from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.schemas import (
    LeadSummary,
    LeadsResponse,
    RunRequest,
    RunResponse,
    RunStatus,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/runs", response_model=RunResponse, status_code=202)
def create_run(req: RunRequest, background_tasks: BackgroundTasks) -> RunResponse:
    """
    Submit a lead generation run.

    Dispatch order:
    1. Celery task (if available) — distributed, retriable, scalable.
    2. BackgroundTasks (FastAPI) — in-process fallback.
    """
    from common.sanitise import sanitise_query

    try:
        query = sanitise_query(req.query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    session_id = str(uuid.uuid4())

    if _try_dispatch_celery(session_id, query, req):
        status = "queued"
    else:
        background_tasks.add_task(_execute_run, session_id, query, req)
        status = "running"

    return RunResponse(
        session_id=session_id,
        status=status,
        leads_url=f"/api/v1/runs/{session_id}/leads",
        status_url=f"/api/v1/runs/{session_id}/status",
    )


@router.get("/runs/{session_id}/status", response_model=RunStatus)
def get_run_status(session_id: str) -> RunStatus:
    """Poll run status and tier counts from the database."""
    import common.db as db
    from common.db.repositories import SessionRepository

    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.read_session() as orm_db:
        session = SessionRepository(orm_db).get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return RunStatus(
        session_id=session_id,
        status=session.status,
        total_leads=session.total_leads or 0,
        hot_count=session.hot_count or 0,
        warm_count=session.warm_count or 0,
        cold_count=session.cold_count or 0,
    )


@router.get("/runs/{session_id}/leads", response_model=LeadsResponse)
def get_run_leads(
    session_id: str,
    tier: str | None = None,
    limit: int = 50,
) -> LeadsResponse:
    """Retrieve scored leads for a completed run."""
    import common.db as db
    from common.db.repositories import LeadRepository

    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.read_session() as orm_db:
        leads = LeadRepository(orm_db).list_by_session(session_id)

    if tier:
        leads = [l for l in leads if l.lead_tier == tier]

    leads = leads[:limit]
    summaries = [
        LeadSummary(
            domain=l.domain,
            company_name=l.company_name or "",
            lead_tier=l.lead_tier or "cold",
            icp_relevance_score=l.icp_relevance_score or 0.0,
            tech_stack=l.tech_stack or [],
            company_summary=l.company_summary or "",
            outreach_subject="",
            source_url=l.source_url or "",
        )
        for l in leads
    ]
    return LeadsResponse(session_id=session_id, total=len(summaries), leads=summaries)


def _try_dispatch_celery(session_id: str, query: str, req: RunRequest) -> bool:
    """Dispatch to Celery if available. Returns True on success."""
    try:
        from tasks.pipeline_task import run_pipeline_task

        if run_pipeline_task is None:
            return False

        overrides = {
            "providers": req.providers or [],
            "max_leads": req.max_leads,
            "crawler": req.crawler,
            "no_crawl": req.no_crawl,
            "no_llm_scoring": req.no_llm_scoring,
            "webhook_url": req.webhook_url or "",
        }
        run_pipeline_task.delay(query, session_id, overrides)
        return True
    except Exception as exc:
        logger.warning("Celery dispatch failed (%s) — using BackgroundTasks", exc)
        return False


def _execute_run(session_id: str, query: str, req: RunRequest) -> None:
    """In-process fallback when Celery is unavailable."""
    try:
        from tasks.pipeline_task import run_pipeline

        overrides = {
            "providers": req.providers or [],
            "max_leads": req.max_leads,
            "crawler": req.crawler,
            "no_crawl": req.no_crawl,
            "no_llm_scoring": req.no_llm_scoring,
            "webhook_url": req.webhook_url or "",
        }
        run_pipeline(query, session_id, overrides)
    except Exception as exc:
        logger.error("Background run %s failed: %s", session_id, exc)
