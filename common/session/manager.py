from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PARTIAL = "partial"  # interrupted mid-run
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Session:
    id: str
    query: str
    status: SessionStatus = SessionStatus.CREATED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None

    # Lead counts
    total_leads: int = 0
    hot_count: int = 0
    warm_count: int = 0
    cold_count: int = 0

    # Pipeline metadata
    pipeline_ms: float = 0.0
    provider_count: int = 0
    crawled_count: int = 0
    error: str | None = None

    # For resumability
    processed_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        d = dict(d)
        d["status"] = SessionStatus(d.get("status", "created"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class SessionManager:
    """
    Creates, persists, and retrieves pipeline sessions.

    Storage: Redis (primary) + in-process dict (fallback / L1 cache).

    Args:
        cache:          A ``LeadCache`` instance (provides Redis backend).
        max_in_memory:  Max sessions to keep in the process dict.
        session_ttl:    Redis TTL for session state (seconds, default 7 days).
    """

    SESSION_TTL = 7 * 86_400  # 7 days

    def __init__(
        self,
        cache=None,  # LeadCache | None
        max_in_memory: int = 50,
        session_ttl: int = SESSION_TTL,
    ) -> None:
        self._cache = cache
        self._ttl = session_ttl
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        self._max_mem = max_in_memory
        # URL sets keyed by session_id (in-memory only — large sets stay in Redis)
        self._url_sets: dict[str, set[str]] = {}

    def create(self, query: str) -> Session:
        """Create a new session and persist it."""
        session = Session(id=str(uuid.uuid4()), query=query)
        self._save(session)
        logger.info("Session created: %s", session.id)
        return session

    def get(self, session_id: str) -> Session | None:
        """Return a session by ID, or ``None`` if not found."""
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]

        # Try cache
        if self._cache:
            state = self._cache.get_session_state(session_id)
            if state:
                session = Session.from_dict(state)
                with self._lock:
                    self._sessions[session_id] = session
                return session

        return None

    def get_or_create(self, query: str, session_id: str | None = None) -> Session:
        """
        Return an existing session by ``session_id`` if found,
        otherwise create a new one for ``query``.
        """
        if session_id:
            existing = self.get(session_id)
            if existing and existing.status != SessionStatus.FAILED:
                logger.info("Resuming session %s (%s)", session_id, existing.status.value)
                return existing
        return self.create(query)

    def update(self, session_id: str, **kwargs: Any) -> Session | None:
        """Update fields on an existing session and re-persist."""
        session = self.get(session_id)
        if session is None:
            logger.warning("update() called on unknown session %s", session_id)
            return None

        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)

        session.updated_at = datetime.now(timezone.utc).isoformat()
        self._save(session)
        return session

    def mark_completed(self, session_id: str, **kwargs: Any) -> None:
        """Transition session to COMPLETED status."""
        self.update(
            session_id,
            status=SessionStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc).isoformat(),
            **kwargs,
        )

    def mark_failed(self, session_id: str, error: str) -> None:
        """Transition session to FAILED status."""
        self.update(
            session_id,
            status=SessionStatus.FAILED,
            error=error,
        )

    def add_processed_url(self, session_id: str, url: str) -> None:
        """Mark a URL as processed in this session."""
        with self._lock:
            s = self._url_sets.setdefault(session_id, set())
            s.add(url)

    def get_processed_urls(self, session_id: str) -> set[str]:
        """Return all URLs already processed in this session."""
        with self._lock:
            return set(self._url_sets.get(session_id, set()))

    def is_url_processed(self, session_id: str, url: str) -> bool:
        with self._lock:
            return url in self._url_sets.get(session_id, set())

    def _save(self, session: Session) -> None:
        with self._lock:
            self._sessions[session.id] = session
            # Evict oldest if over capacity
            if len(self._sessions) > self._max_mem:
                oldest = next(iter(self._sessions))
                del self._sessions[oldest]

        if self._cache:
            self._cache.set_session_state(session.id, session.to_dict(), ttl=self._ttl)

    @classmethod
    def from_config(cls, config, cache=None) -> "SessionManager":
        return cls(
            cache=cache,
            max_in_memory=config.session.max_sessions_in_memory,
            session_ttl=config.session.session_ttl,
        )
