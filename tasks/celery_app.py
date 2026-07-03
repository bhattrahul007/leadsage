from __future__ import annotations

import os


def _make_celery():
    """
    Build the Celery app instance.

    Broker + backend: Redis (already in the stack).
    Raises ImportError gracefully if celery is not installed.
    """
    try:
        from celery import Celery
    except ImportError:
        return None

    broker = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6379/1"))
    backend = os.getenv("CELERY_RESULT_BACKEND", broker)

    app = Celery(
        "prospector",
        broker=broker,
        backend=backend,
        include=["tasks.pipeline_task"],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,  # fair dispatch
        task_soft_time_limit=360,  # 6 min soft limit
        task_time_limit=420,  # 7 min hard kill
        result_expires=86_400,  # results kept 24h
    )
    return app


celery_app = _make_celery()
