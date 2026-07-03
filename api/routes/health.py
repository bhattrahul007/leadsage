from fastapi import APIRouter
from api.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    import common.db as db

    db_status = "ok" if db.is_available() else "unavailable"

    redis_status = "unavailable"
    try:
        import redis as redis_lib
        from common.config import load_config

        cfg = load_config()
        if cfg.session.redis_enabled:
            r = redis_lib.from_url(cfg.session.redis_url, socket_connect_timeout=1)
            r.ping()
            redis_status = "ok"
    except Exception:
        pass

    return HealthResponse(db=db_status, redis=redis_status, status="ok")
