from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from common.context.window import SummaryBufferWindow

logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ConversationMessage:
    role: Literal["user", "assistant", "system"]
    content: str
    agent_name: str | None = None
    model_name: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ConversationMessage":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Session:
    id: str
    query: str
    status: SessionStatus = SessionStatus.CREATED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None

    total_leads: int = 0
    hot_count: int = 0
    warm_count: int = 0
    cold_count: int = 0

    pipeline_ms: float = 0.0
    provider_count: int = 0
    crawled_count: int = 0
    error: str | None = None

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
    SESSION_TTL = 7 * 86_400

    def __init__(
        self,
        cache=None,
        max_in_memory: int = 100,
        session_ttl: int = SESSION_TTL,
        conversation_history_limit: int = 50,
        conversation_ttl: int = 30 * 86_400,
    ) -> None:
        self._cache = cache
        self._ttl = session_ttl
        self._conv_limit = conversation_history_limit
        self._conv_ttl = conversation_ttl
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        self._max_mem = max_in_memory
        self._url_sets: dict[str, set[str]] = {}
        self._conversations: dict[str, list[ConversationMessage]] = {}
        # Optional SummaryBufferWindow per session (set via attach_context_window)
        self._context_window: dict[str, Any] = {}

    def create(self, query: str) -> Session:
        session = Session(id=str(uuid.uuid4()), query=query)
        self._save(session)
        logger.info("Session created: %s", session.id)
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]

        if self._cache:
            state = self._cache.get_session_state(session_id)
            if state:
                session = Session.from_dict(state)
                with self._lock:
                    self._sessions[session_id] = session
                return session

        return None

    def get_or_create(self, query: str, session_id: str | None = None) -> Session:
        if session_id:
            existing = self.get(session_id)
            if existing and existing.status != SessionStatus.FAILED:
                logger.info("Resuming session %s (%s)", session_id, existing.status.value)
                return existing
        return self.create(query)

    def update(self, session_id: str, **kwargs: Any) -> Session | None:
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
        self.update(
            session_id,
            status=SessionStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc).isoformat(),
            **kwargs,
        )

    def mark_failed(self, session_id: str, error: str) -> None:
        self.update(session_id, status=SessionStatus.FAILED, error=error)

    def add_processed_url(self, session_id: str, url: str) -> None:
        with self._lock:
            s = self._url_sets.setdefault(session_id, set())
            s.add(url)

    def get_processed_urls(self, session_id: str) -> set[str]:
        with self._lock:
            return set(self._url_sets.get(session_id, set()))

    def is_url_processed(self, session_id: str, url: str) -> bool:
        with self._lock:
            return url in self._url_sets.get(session_id, set())

    # ──────────────────────────────────────────────────────────────────
    # Conversation history
    # ──────────────────────────────────────────────────────────────────

    def add_conversation_turn(
        self,
        session_id: str,
        role: Literal["user", "assistant", "system"],
        content: str,
        agent_name: str | None = None,
        model_name: str | None = None,
    ) -> ConversationMessage:
        msg = ConversationMessage(
            role=role,
            content=content,
            agent_name=agent_name,
            model_name=model_name,
        )
        with self._lock:
            history = self._conversations.setdefault(session_id, [])
            history.append(msg)
            # Trim in-memory to limit (DB keeps the full log)
            if len(history) > self._conv_limit:
                self._conversations[session_id] = history[-self._conv_limit :]

        # Mirror to SummaryBufferWindow if wired
        if self._context_window and session_id in self._context_window:
            self._context_window[session_id].add(role, content, agent=agent_name)

        self._persist_conversation(session_id)
        return msg

    def get_conversation_history(
        self,
        session_id: str,
        last_n: int | None = None,
    ) -> list[ConversationMessage]:
        with self._lock:
            if session_id in self._conversations:
                history = list(self._conversations[session_id])
                return history[-last_n:] if last_n else history

        history = self._load_conversation(session_id)
        if history:
            with self._lock:
                self._conversations[session_id] = history
            return history[-last_n:] if last_n else history

        return []

    def clear_conversation_history(self, session_id: str) -> None:
        with self._lock:
            self._conversations.pop(session_id, None)
        if self._cache and self._cache._redis and self._cache._redis.available:
            try:
                self._cache._redis.delete(f"conv:{session_id}")
            except Exception:
                pass

    def get_conversation_context(
        self,
        session_id: str,
        last_n: int = 10,
    ) -> str:
        history = self.get_conversation_history(session_id, last_n=last_n)
        if not history:
            return ""
        lines = []
        for msg in history:
            prefix = {"user": "Human", "assistant": "Assistant", "system": "System"}.get(
                msg.role, msg.role
            )
            lines.append(f"{prefix}: {msg.content}")
        return "\n".join(lines)

    def _persist_conversation(self, session_id: str) -> None:
        if not (self._cache and self._cache._redis and self._cache._redis.available):
            return
        with self._lock:
            history = self._conversations.get(session_id, [])
        try:
            import gzip

            payload = json.dumps([m.to_dict() for m in history], ensure_ascii=False)
            compressed = gzip.compress(payload.encode(), compresslevel=6)
            self._cache._redis.set(f"conv:{session_id}", compressed, self._conv_ttl)
        except Exception as exc:
            logger.debug("Conversation persist error: %s", exc)

    def _load_conversation(self, session_id: str) -> list[ConversationMessage]:
        if not (self._cache and self._cache._redis and self._cache._redis.available):
            return []
        try:
            import gzip

            data = self._cache._redis.get(f"conv:{session_id}")
            if data:
                payload = json.loads(gzip.decompress(data).decode())
                return [ConversationMessage.from_dict(m) for m in payload]
        except Exception as exc:
            logger.debug("Conversation load error: %s", exc)
        return []

    def _save(self, session: Session) -> None:
        with self._lock:
            self._sessions[session.id] = session
            if len(self._sessions) > self._max_mem:
                oldest = next(iter(self._sessions))
                del self._sessions[oldest]

        if self._cache:
            self._cache.set_session_state(session.id, session.to_dict(), ttl=self._ttl)

    def attach_context_window(self, session_id: str, window: "SummaryBufferWindow") -> None:
        """Wire a SummaryBufferWindow to a session for auto-mirroring."""
        self._context_window[session_id] = window

    def get_agent_context(self, session_id: str, budget_tokens: int = 2000) -> str:
        """
        Return a rich context string for agent prompts.

        Uses the SummaryBufferWindow if available (summary + recent turns),
        otherwise falls back to plain conversation history.
        """
        if session_id in self._context_window:
            return self._context_window[session_id].get_context(budget_tokens)
        return self.get_conversation_context(session_id, last_n=10)

    @classmethod
    def from_config(cls, config, cache=None) -> "SessionManager":
        return cls(
            cache=cache,
            max_in_memory=config.session.max_sessions_in_memory,
            session_ttl=config.session.session_ttl,
            conversation_history_limit=config.session.conversation_history_limit,
            conversation_ttl=config.session.conversation_ttl,
        )
