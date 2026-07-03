from __future__ import annotations

import itertools
import logging
import os
import threading

logger = logging.getLogger(__name__)


class KeyRing:
    """
    Round-robin API key pool.

    Loads a primary key from ``primary_env`` and additional keys from
    ``{extra_prefix}_1``, ``{extra_prefix}_2``, etc.

    Example::

        ring = KeyRing("SERPER_API_KEY", extra_prefix="SERPER_API_KEY")
        key = ring.next_key()   # rotates on each call
    """

    def __init__(self, primary_env: str, extra_prefix: str | None = None) -> None:
        keys: list[str] = []

        primary = os.getenv(primary_env, "").strip()
        if primary:
            keys.append(primary)

        prefix = extra_prefix or primary_env
        index = 1
        while True:
            extra = os.getenv(f"{prefix}_{index}", "").strip()
            if not extra:
                break
            keys.append(extra)
            index += 1

        self._keys = keys
        self._cycle = itertools.cycle(keys) if keys else iter([])
        self._lock = threading.Lock()

        if keys:
            logger.debug("KeyRing[%s] loaded %d key(s).", primary_env, len(keys))

    @property
    def available(self) -> bool:
        return bool(self._keys)

    def next_key(self) -> str:
        if not self._keys:
            raise OSError("No API keys loaded. Check your environment variables.")
        with self._lock:
            return next(self._cycle)

    def __len__(self) -> int:
        return len(self._keys)
