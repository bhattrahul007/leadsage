"""
discovery.crawlers
~~~~~~~~~~~~~~~~~~
Extensible crawler layer with Factory + Decorator patterns.

Crawlers available::

    "requests"    — requests + html.parser (fast, no JS) — default
    "playwright"  — headless Chromium (JS-rendered pages) — optional

Wrap any crawler with proxy rotation::

    from discovery.crawlers import CrawlerFactory
    from common.proxy import ProxyProviderFactory

    crawler = CrawlerFactory.create("requests", config)
    # or with proxy:
    crawler = CrawlerFactory.create_with_proxy("requests", config, proxy_provider)
"""

from discovery.crawlers.base import BaseCrawler
from discovery.crawlers.factory import CrawlerFactory, register_crawler
from discovery.crawlers.proxy_crawler import ProxiedCrawler

__all__ = [
    "BaseCrawler",
    "CrawlerFactory",
    "register_crawler",
    "ProxiedCrawler",
]
