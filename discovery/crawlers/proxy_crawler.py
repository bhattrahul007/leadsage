from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from discovery.crawler import CrawledPage
from discovery.crawlers.base import BaseCrawler

if TYPE_CHECKING:
    from common.proxy.base import BaseProxyProvider, ProxyDict

logger = logging.getLogger(__name__)

_PROXY_BLOCK_CODES: frozenset[int] = frozenset(
    {
        403,  # Forbidden (often geo-block or bot detection)
        407,  # Proxy authentication required
        429,  # Rate limited at proxy level
        503,  # Service unavailable (sometimes proxy issue)
    }
)

# Error message substrings that indicate proxy issues
_PROXY_ERROR_HINTS: tuple[str, ...] = (
    "proxyerror",
    "407",
    "proxy",
    "tunnel",
    "captcha",
    "blocked",
    "banned",
    "access denied",
    "cloudflare",
)


class ProxiedCrawler(BaseCrawler):
    """
    Decorator that wraps any ``BaseCrawler`` with transparent proxy rotation.

    Behaviour
    ---------
    1. Before each ``crawl()`` call, acquire a proxy from the provider.
    2. Pass the proxy to the inner crawler's ``crawl()`` method.
    3. If the crawl fails and the error looks proxy-related:
       a. Report the failure to the provider (may quarantine that proxy).
       b. Rotate to a fresh proxy.
       c. Retry the crawl once with the new proxy.
    4. Return the ``CrawledPage`` result (success or failure).

    Args:
        inner:          The underlying ``BaseCrawler`` implementation.
        proxy_provider: The ``BaseProxyProvider`` to use for proxy acquisition.
        max_retries:    Max proxy rotation attempts per URL (default 2).
    """

    def __init__(
        self,
        inner: BaseCrawler,
        proxy_provider: "BaseProxyProvider",
        max_retries: int = 2,
    ) -> None:
        self._inner = inner
        self._proxy_provider = proxy_provider
        self._max_retries = max_retries

    @property
    def crawler_type(self) -> str:
        return f"proxied_{self._inner.crawler_type}"

    def crawl(
        self,
        url: str,
        proxy: "ProxyDict | None" = None,
    ) -> CrawledPage:
        """
        Crawl ``url`` with automatic proxy acquisition and rotation.

        The ``proxy`` argument overrides the provider for this single call
        (useful for ProxyCrawler-in-ProxyCrawler nesting, rare but supported).
        """
        p = proxy or self._proxy_provider.get_proxy()
        page = self._inner.crawl(url, proxy=p)

        attempts = 0
        while not page.success and _is_proxy_error(page) and attempts < self._max_retries:
            attempts += 1
            reason = f"status={page.status_code} error={page.error}"
            logger.info("Proxy issue on %s (attempt %d): %s — rotating", url, attempts, reason)
            self._proxy_provider.report_failure(p, reason)
            p = self._proxy_provider.rotate()
            page = self._inner.crawl(url, proxy=p)

        return page

    def crawl_many(
        self,
        urls: list[str],
        max_workers: int = 10,
        proxy_provider: "BaseProxyProvider | None" = None,
    ) -> list[CrawledPage]:
        """
        Delegate to inner crawler's ``crawl_many()`` using this crawler's
        provider (or the overriding ``proxy_provider`` if given).
        """
        effective_provider = proxy_provider or self._proxy_provider
        return self._inner.crawl_many(
            urls,
            max_workers=max_workers,
            proxy_provider=effective_provider,
        )

    def __repr__(self) -> str:
        return f"<ProxiedCrawler inner={self._inner!r} provider={self._proxy_provider.name!r}>"


def _is_proxy_error(page: CrawledPage) -> bool:
    """Heuristic: did this crawl fail because of a proxy issue?"""
    if page.status_code in _PROXY_BLOCK_CODES:
        return True
    error_lower = (page.error or "").lower()
    return any(hint in error_lower for hint in _PROXY_ERROR_HINTS)
