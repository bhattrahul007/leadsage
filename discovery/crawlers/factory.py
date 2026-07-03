from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from discovery.crawlers.base import BaseCrawler

if TYPE_CHECKING:
    from common.proxy.base import BaseProxyProvider
    from discovery.crawler import CrawlerConfig

logger = logging.getLogger(__name__)

# Registry: slug → crawler class
_CRAWLER_REGISTRY: dict[str, type[BaseCrawler]] = {}


def register_crawler(name: str):
    """
    Class decorator to register a crawler under ``name``.
    """

    def decorator(cls: type[BaseCrawler]) -> type[BaseCrawler]:
        _CRAWLER_REGISTRY[name] = cls
        logger.debug("Registered crawler: %s → %s", name, cls.__name__)
        return cls

    return decorator


class CrawlerFactory:
    """
    Creates ``BaseCrawler`` instances by name from config.
    """

    @staticmethod
    def _ensure_registered() -> None:
        """Import all built-in crawlers to trigger their decorators."""
        from discovery.crawlers import requests_crawler  # noqa: F401

        try:
            from discovery.crawlers import playwright_crawler  # noqa: F401
        except ImportError:
            pass  # Playwright optional

    @classmethod
    def create(
        cls,
        crawler_type: str,
        config: "CrawlerConfig | None" = None,
    ) -> BaseCrawler:
        """
        Instantiate a crawler by type slug.

        Args:
            crawler_type: Slug, e.g. ``"requests"``, ``"playwright"``.
            config:       ``CrawlerConfig`` to pass to the crawler.

        Returns:
            A ready-to-use ``BaseCrawler`` instance.

        Raises:
            ValueError: If ``crawler_type`` is not registered.
        """
        cls._ensure_registered()

        if crawler_type not in _CRAWLER_REGISTRY:
            available = ", ".join(sorted(_CRAWLER_REGISTRY))
            raise ValueError(f"Unknown crawler type: {crawler_type!r}. Available: [{available}]")

        crawler_cls = _CRAWLER_REGISTRY[crawler_type]
        logger.debug("Creating crawler: %s", crawler_type)
        return crawler_cls(config=config)

    @classmethod
    def create_with_proxy(
        cls,
        crawler_type: str,
        config: "CrawlerConfig | None",
        proxy_provider: "BaseProxyProvider",
    ) -> BaseCrawler:
        """
        Create a crawler wrapped in ``ProxiedCrawler``.

        Args:
            crawler_type:   Underlying crawler slug.
            config:         Crawler config.
            proxy_provider: Proxy backend to use.

        Returns:
            A ``ProxiedCrawler`` wrapping the underlying crawler.
        """
        from discovery.crawlers.proxy_crawler import ProxiedCrawler

        inner = cls.create(crawler_type, config)
        return ProxiedCrawler(inner=inner, proxy_provider=proxy_provider)

    @classmethod
    def registered(cls) -> list[str]:
        """Return names of all registered crawlers."""
        cls._ensure_registered()
        return sorted(_CRAWLER_REGISTRY)
