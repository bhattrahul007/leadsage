from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import gzip
import json
import logging
import threading
from typing import Any, Literal

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 4


def _tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


@dataclass
class Turn:
    role: Literal["user", "assistant", "system"]
    content: str
    agent: str | None = None
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Turn:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @property
    def token_count(self) -> int:
        return _tokens(self.content)


class SummaryBufferWindow:
    """3-tier hierarchical memory for long-running agent sessions.

    L0: in-process deque (max_turns, zero-latency).
    L1: Redis gzip-compressed (survives process restart, TTL=24h).
    L2: PostgreSQL (permanent log, written externally).

    When the L0 buffer exceeds max_tokens, the oldest chunk_size turns are
    compacted into a rolling summary and dropped from the deque.
    """

    DEFAULT_MAX_TOKENS = 6_000
    DEFAULT_MAX_TURNS = 40
    DEFAULT_CHUNK = 10

    def __init__(
        self,
        session_id: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_turns: int = DEFAULT_MAX_TURNS,
        chunk_size: int = DEFAULT_CHUNK,
        summarizer_fn: Callable[[str], str] | None = None,
        redis_backend=None,
        ttl: int = 86_400,
        emit_fn: Callable[[Any], None] | None = None,
    ) -> None:
        self._sid = session_id
        self._max_tokens = max_tokens
        self._max_turns = max_turns
        self._chunk = chunk_size
        self._summarize = summarizer_fn
        self._redis = redis_backend
        self._ttl = ttl
        self._emit = emit_fn
        self._lock = threading.Lock()

        self._buffer: deque[Turn] = deque(maxlen=max_turns)
        self._rolling_summary: str = ""
        self._total_tokens: int = 0

        self._load_from_redis()

    def add(
        self,
        role: Literal["user", "assistant", "system"],
        content: str,
        agent: str | None = None,
    ) -> Turn:
        """Append a turn; triggers compaction if over token budget."""
        turn = Turn(role=role, content=content, agent=agent)
        with self._lock:
            self._buffer.append(turn)
            self._total_tokens += turn.token_count
            if self._total_tokens > self._max_tokens:
                self._compact()
        self._persist()
        return turn

    def get_context(self, budget_tokens: int | None = None) -> str:
        """Return a context string within budget_tokens tokens.

        Prepends the rolling summary, then recent turns newest-first.
        """
        budget = budget_tokens or self._max_tokens
        with self._lock:
            lines: list[str] = []
            token_used = 0

            if self._rolling_summary:
                prefix = f"[Context summary]\n{self._rolling_summary}\n\n[Recent conversation]"
                lines.append(prefix)
                token_used += _tokens(prefix)

            for turn in reversed(self._buffer):
                label = {"user": "Human", "assistant": "Assistant"}.get(turn.role, turn.role)
                line = f"{label}: {turn.content}"
                if token_used + turn.token_count > budget:
                    break
                lines.append(line)
                token_used += turn.token_count

            if self._rolling_summary:
                ordered = [lines[0]] + list(reversed(lines[1:]))
            else:
                ordered = list(reversed(lines))

        return "\n".join(ordered)

    def get_recent(self, n: int = 10) -> list[Turn]:
        with self._lock:
            return list(self._buffer)[-n:]

    def update_rolling_summary(self, addition: str) -> None:
        """Append a signal update to the rolling summary (e.g. from ICP refiner)."""
        with self._lock:
            self._rolling_summary = f"{self._rolling_summary}\n{addition}".strip()[-2000:]
        self._persist()

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "turns_in_buffer": len(self._buffer),
                "estimated_tokens": self._total_tokens,
                "has_summary": bool(self._rolling_summary),
                "summary_chars": len(self._rolling_summary),
            }

    def _compact(self) -> None:
        """Summarize the oldest chunk and drop it from the buffer."""
        if len(self._buffer) < self._chunk:
            return

        old_turns = [self._buffer.popleft() for _ in range(self._chunk)]
        self._total_tokens -= sum(t.token_count for t in old_turns)

        chunk_text = "\n".join(f"{t.role}: {t.content}" for t in old_turns)
        if self._summarize:
            try:
                summary = self._summarize(chunk_text)
            except Exception:
                summary = f"[{len(old_turns)} turns summarized]"
        else:
            summary = _extractive_summary(chunk_text)

        self._rolling_summary = f"{self._rolling_summary}\n{summary}".strip()[-4000:]

        logger.debug(
            "[SummaryBufferWindow:%s] compacted %d turns → %d summary chars",
            self._sid[:8],
            len(old_turns),
            len(summary),
        )

        if self._emit:
            try:
                from common.events.events import ContextCompressed

                self._emit(
                    ContextCompressed(
                        session_id=self._sid,
                        turns_compacted=len(old_turns),
                        summary_preview=summary[:120],
                        new_summary_chars=len(self._rolling_summary),
                    )
                )
            except Exception:
                pass

    def _persist(self) -> None:
        if not (self._redis and self._redis.available):
            return
        try:
            payload = {
                "summary": self._rolling_summary,
                "buffer": [t.to_dict() for t in self._buffer],
            }
            raw = gzip.compress(json.dumps(payload, ensure_ascii=False).encode(), compresslevel=6)
            self._redis.set(f"ctx:{self._sid}", raw, self._ttl)
        except Exception as exc:
            logger.debug("SummaryBufferWindow persist error: %s", exc)

    def _load_from_redis(self) -> None:
        if not (self._redis and self._redis.available):
            return
        try:
            raw = self._redis.get(f"ctx:{self._sid}")
            if not raw:
                return
            payload = json.loads(gzip.decompress(raw))
            self._rolling_summary = payload.get("summary", "")
            for d in payload.get("buffer", []):
                t = Turn.from_dict(d)
                self._buffer.append(t)
                self._total_tokens += t.token_count
        except Exception as exc:
            logger.debug("SummaryBufferWindow load error: %s", exc)


def _extractive_summary(text: str, max_chars: int = 400) -> str:
    """Fallback: keep first + last sentence when no LLM summarizer."""
    sentences = [s.strip() for s in text.split(".") if s.strip()]
    if not sentences:
        return text[:max_chars]
    if len(sentences) <= 2:
        return ". ".join(sentences[:2])
    return f"{sentences[0]}. … {sentences[-1]}."
