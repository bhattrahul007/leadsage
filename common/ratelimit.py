from __future__ import annotations

import threading
import time


class TokenBucket:
    """Thread-safe token bucket for rate limiting (tokens refilled per minute)."""

    def __init__(self, rpm: int) -> None:
        self._capacity = max(1, rpm)
        self._tokens = float(self._capacity)
        self._refill_rate = self._capacity / 60.0  # tokens per second
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now


class RateLimiterRegistry:
    """Process-wide registry mapping provider names to TokenBuckets."""

    _limiters: dict[str, TokenBucket] = {}
    _lock = threading.Lock()

    @classmethod
    def configure(cls, limits: dict[str, int]) -> None:
        with cls._lock:
            for name, rpm in limits.items():
                if rpm > 0:
                    cls._limiters[name] = TokenBucket(rpm)

    @classmethod
    def acquire(cls, provider: str, timeout: float = 30.0) -> bool:
        limiter = cls._limiters.get(provider)
        if limiter is None:
            return True
        return limiter.acquire(timeout=timeout)

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._limiters.clear()
