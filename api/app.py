from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health, runs, stream


def create_app() -> FastAPI:
    app = FastAPI(
        title="Prospector API",
        description="AI Lead Generation — REST interface",
        version="0.3.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, tags=["Health"])
    app.include_router(runs.router, prefix="/api/v1", tags=["Runs"])
    app.include_router(stream.router, prefix="/api/v1", tags=["Streaming"])

    @app.on_event("startup")
    def _startup():
        from common.config import load_config
        import common.db as db
        from common.ratelimit import RateLimiterRegistry

        cfg = load_config()
        RateLimiterRegistry.configure(cfg.rate_limits.to_dict())

        db_url = db.get_database_url()
        if db_url:
            try:
                db.init_engine(db_url)
            except Exception:
                pass

    return app


# Module-level app instance for uvicorn
app = create_app()
