from __future__ import annotations

import concurrent.futures
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from discovery.crawler import CrawlerConfig, ExtractedMeta, WebCrawler
from discovery.crawler import CrawledPage
from discovery.crawlers.base import BaseCrawler
from discovery.crawlers.factory import register_crawler

if TYPE_CHECKING:
    from common.proxy.base import BaseProxyProvider, ProxyDict

logger = logging.getLogger(__name__)


@register_crawler("requests")
class RequestsCrawler(BaseCrawler):
    """
    Production-ready requests-based crawler with retry and proxy support.

    Wraps the battle-tested ``WebCrawler`` implementation and exposes the
    ``BaseCrawler`` interface so it can be swapped via config.

    Args:
        config: ``CrawlerConfig`` controlling timeout, user-agent, etc.

    Example::

        crawler = RequestsCrawler(CrawlerConfig(timeout=10))
        page = crawler.crawl("https://example.com")
    """

    def __init__(self, config: CrawlerConfig | None = None) -> None:
        self._config = config or CrawlerConfig()
        self._inner = WebCrawler(self._config)

    def crawl(
        self,
        url: str,
        proxy: "ProxyDict | None" = None,
    ) -> CrawledPage:
        """
        Fetch and parse ``url``.

        If ``proxy`` is provided it is injected into the underlying session
        for this single request (thread-safe via a per-call approach).
        """
        if proxy:
            # Create a temporary crawler with proxy injected into its session
            return self._crawl_with_proxy(url, proxy)
        return self._inner.crawl(url)

    def crawl_many(
        self,
        urls: list[str],
        max_workers: int = 10,
        proxy_provider: "BaseProxyProvider | None" = None,
    ) -> list[CrawledPage]:
        """Crawl multiple URLs concurrently, optionally with per-URL proxies."""
        if not urls:
            return []

        results: dict[str, CrawledPage] = {}

        def _fetch(url: str) -> tuple[str, CrawledPage]:
            proxy = proxy_provider.get_proxy() if proxy_provider else None
            page = self.crawl(url, proxy=proxy)
            if not page.success and proxy_provider and proxy:
                proxy_provider.report_failure(proxy, page.error or "crawl failed")
                new_proxy = proxy_provider.rotate()
                page = self.crawl(url, proxy=new_proxy)
            return url, page

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="req_crawler",
        ) as pool:
            futures = {pool.submit(_fetch, url): url for url in urls}
            for future in concurrent.futures.as_completed(futures):
                orig_url = futures[future]
                try:
                    key, page = future.result()
                    results[key] = page
                except Exception as exc:
                    logger.error("Crawler error for %s: %s", orig_url, exc)
                    results[orig_url] = _error_page(orig_url, str(exc))

        return [results.get(u, _error_page(u, "missing")) for u in urls]

    # ------------------------------------------------------------------

    def _crawl_with_proxy(self, url: str, proxy: "ProxyDict") -> CrawledPage:
        """
        Inject proxy into the requests session for a single call.

        We temporarily patch the session's proxies dict for this request.
        Since this may be called from multiple threads, we use a fresh
        session per proxy-injected call to stay thread-safe.
        """
        import requests
        import time
        from common.retry import RetryConfig, retry_with_config

        cfg = self._config
        start = time.perf_counter()
        fetched_at = datetime.now(timezone.utc).isoformat()

        session = requests.Session()
        session.headers.update({"User-Agent": cfg.user_agent})
        session.proxies.update(proxy)

        try:
            resp = session.get(
                url,
                timeout=cfg.timeout,
                stream=True,
                allow_redirects=True,
            )
            resp.raise_for_status()
            latency_ms = (time.perf_counter() - start) * 1000

            raw = b""
            for chunk in resp.iter_content(chunk_size=8192):
                raw += chunk
                if len(raw) >= cfg.max_content_bytes:
                    break

            # Delegate parsing to the original WebCrawler's internals
            # by temporarily replacing the session — cleanest approach
            # without duplicating parsing logic
            html = raw.decode("utf-8", errors="replace")
            final_url = resp.url

            from discovery.crawler import _PageParser, _build_meta

            parser = _PageParser(final_url, max_links=cfg.max_links)
            parser.feed(html)
            raw_text = parser.text
            meta = _build_meta(parser, raw_text, cfg.extract_tech)

            return CrawledPage(
                url=url,
                final_url=final_url,
                status_code=resp.status_code,
                title=parser.title.strip(),
                text_content=raw_text,
                meta=meta,
                links=parser.links,
                crawled_at=fetched_at,
                latency_ms=latency_ms,
                success=True,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.warning("Proxy crawl failed for %s: %s", url, exc)
            return _error_page(url, str(exc), latency_ms=latency_ms)
        finally:
            session.close()


def _error_page(url: str, error: str, latency_ms: float = 0.0) -> CrawledPage:
    return CrawledPage(
        url=url,
        final_url=url,
        status_code=0,
        title="",
        text_content="",
        meta=ExtractedMeta(),
        links=[],
        crawled_at=datetime.now(timezone.utc).isoformat(),
        latency_ms=latency_ms,
        success=False,
        error=error,
    )
