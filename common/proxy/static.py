from __future__ import annotations

import logging
import threading
import time

from common.proxy.base import BaseProxyProvider, ProxyDict
from common.proxy.factory import register_proxy_provider

logger = logging.getLogger(__name__)


@register_proxy_provider("static")
class StaticProxyProvider(BaseProxyProvider):
    """
    Round-robin over a fixed list of proxy URLs.

    Thread-safe. Failed proxies are quarantined (skipped) for
    ``quarantine_seconds``, then re-added to the rotation.
    """

    name = "static"

    def __init__(
        self,
        proxy_urls: list[str],
        quarantine_seconds: float = 300.0,
    ) -> None:
        if not proxy_urls:
            raise ValueError("StaticProxyProvider requires at least one proxy URL")

        self._all_proxies = list(proxy_urls)
        self._quarantine_secs = quarantine_seconds
        self._quarantined: dict[str, float] = {}  # proxy_url → quarantine_until ts
        self._lock = threading.Lock()
        self._rotations = 0
        self._failures = 0
        self._current: str | None = None
        self._rotate_to_next()

    def get_proxy(self) -> ProxyDict:
        with self._lock:
            if self._current is None:
                self._rotate_to_next()
            url = self._current or self._all_proxies[0]
            return _url_to_dict(url)

    def rotate(self) -> ProxyDict:
        with self._lock:
            self._rotations += 1
            self._rotate_to_next(skip_current=True)
            url = self._current or self._all_proxies[0]
            logger.debug("StaticProxy rotated → %s", _mask(url))
            return _url_to_dict(url)

    def report_failure(self, proxy: ProxyDict, error: str = "") -> None:
        with self._lock:
            self._failures += 1
            # Find which URL corresponds to this proxy dict
            url = _dict_to_url(proxy)
            if url:
                self._quarantined[url] = time.monotonic() + self._quarantine_secs
                logger.warning(
                    "StaticProxy quarantined %s for %.0fs: %s",
                    _mask(url),
                    self._quarantine_secs,
                    error,
                )
            self._rotate_to_next(skip_current=True)

    def health(self) -> dict:
        with self._lock:
            now = time.monotonic()
            active = [u for u in self._all_proxies if now >= self._quarantined.get(u, 0)]
            return {
                "total_proxies": len(self._all_proxies),
                "active_proxies": len(active),
                "quarantined": len(self._all_proxies) - len(active),
                "rotations": self._rotations,
                "failures": self._failures,
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _rotate_to_next(self, skip_current: bool = False) -> None:
        """Advance to the next non-quarantined proxy."""
        now = time.monotonic()
        available = [
            u
            for u in self._all_proxies
            if now >= self._quarantined.get(u, 0) and (not skip_current or u != self._current)
        ]
        if not available:
            # All quarantined — pick the one with the soonest expiry
            available = sorted(
                self._all_proxies,
                key=lambda u: self._quarantined.get(u, 0),
            )
            logger.warning("StaticProxy: all proxies quarantined; using %s", _mask(available[0]))

        self._current = available[0] if available else self._all_proxies[0]


def _url_to_dict(url: str) -> ProxyDict:
    return {"http": url, "https": url}


def _dict_to_url(proxy: ProxyDict) -> str | None:
    return proxy.get("http") or proxy.get("https")


def _mask(url: str) -> str:
    """Mask credentials in a proxy URL for safe logging."""
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        if p.password:
            return url.replace(p.password, "***")
    except Exception:
        pass
    return url
