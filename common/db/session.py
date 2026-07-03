from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from common.db.models import Base

# Primary (write) engine + session factory
_engine = None
_SessionLocal = None

# Optional read-replica engine
_read_engine = None
_ReadSessionLocal = None


def get_database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or _build_url_from_parts()


def _build_url_from_parts() -> str | None:
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB")
    if user and password and db:
        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
    return None


def _make_engine(url: str, pool_size: int, max_overflow: int, pool_timeout: int, echo: bool):
    engine = create_engine(
        url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=3600,
        pool_pre_ping=True,
        echo=echo,
    )

    @event.listens_for(engine, "connect")
    def _set_timezone(dbapi_conn, _):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET timezone = 'UTC'")

    return engine


def init_engine(
    database_url: str | None = None,
    pool_size: int = 20,
    max_overflow: int = 30,
    pool_timeout: int = 10,
    echo: bool = False,
):
    """Initialise the primary (write) engine. Creates tables if absent."""
    global _engine, _SessionLocal

    url = database_url or get_database_url()
    if not url:
        return None

    _engine = _make_engine(url, pool_size, max_overflow, pool_timeout, echo)
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=_engine)
    return _engine


def init_read_replica(read_url: str, pool_size: int = 10, max_overflow: int = 20) -> None:
    """
    Configure a read-replica engine for SELECT-heavy workloads.

    If not called, ``read_session()`` falls back to the primary engine.
    """
    global _read_engine, _ReadSessionLocal

    _read_engine = _make_engine(read_url, pool_size, max_overflow, pool_timeout=10, echo=False)
    _ReadSessionLocal = sessionmaker(bind=_read_engine, autocommit=False, autoflush=False)


def get_engine():
    return _engine


def get_session() -> Generator[Session, None, None]:
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised. Call init_engine() first.")
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class db_session:
    """Write-path session context manager."""

    def __init__(self):
        if _SessionLocal is None:
            raise RuntimeError("Database not initialised. Call init_engine() first.")
        self._db: Session = _SessionLocal()

    def __enter__(self) -> Session:
        return self._db

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._db.rollback()
        else:
            self._db.commit()
        self._db.close()


@contextmanager
def read_session() -> Generator[Session, None, None]:
    """Read-path session — uses replica if configured, otherwise primary."""
    factory = _ReadSessionLocal or _SessionLocal
    if factory is None:
        raise RuntimeError("Database not initialised. Call init_engine() first.")
    db = factory()
    try:
        yield db
    finally:
        db.close()


def is_available() -> bool:
    return _engine is not None
