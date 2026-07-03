from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discovery.crawler import CrawledPage
    from common.proxy.base import BaseProxyProvider, ProxyDict


class BaseCrawler(ABC):
    """
    Abstract web crawler interface.
    """

    @abstractmethod
    def crawl(
        self,
        url: str,
        proxy: "ProxyDict | None" = None,
    ) -> "CrawledPage":
        """
        Fetch and parse a single URL.

        Args:
            url:   The target URL.
            proxy: Optional proxy dict ``{"http": "...", "https": "..."}``.
                   If None, no proxy is used.

        Returns:
            A ``CrawledPage``. Always returns — never raises. On failure,
            ``CrawledPage.success == False`` and ``CrawledPage.error`` is set.
        """
        ...

    @abstractmethod
    def crawl_many(
        self,
        urls: list[str],
        max_workers: int = 10,
        proxy_provider: "BaseProxyProvider | None" = None,
    ) -> list["CrawledPage"]:
        """
        Crawl multiple URLs concurrently.

        Args:
            urls:           List of target URLs.
            max_workers:    Thread pool size.
            proxy_provider: If provided, each URL gets a proxy from the
                            provider (with automatic rotation on failure).

        Returns:
            ``CrawledPage`` list in the same order as ``urls``.
        """
        ...

    @property
    def crawler_type(self) -> str:
        """Slug identifying this crawler implementation."""
        return self.__class__.__name__.lower().replace("crawler", "")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
