from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime
import logging
import time
from typing import TYPE_CHECKING

from discovery.crawler import CrawledPage, CrawlerConfig, ExtractedMeta
from discovery.crawlers.base import BaseCrawler
from discovery.crawlers.factory import register_crawler

if TYPE_CHECKING:
    from common.proxy.base import BaseProxyProvider, ProxyDict

logger = logging.getLogger(__name__)


@register_crawler("playwright")
class PlaywrightCrawler(BaseCrawler):
    """
    Headless Chromium crawler using ``playwright``.

    Args:
        config: ``CrawlerConfig`` (uses timeout, user_agent, max_content_bytes).

    Example::

        crawler = PlaywrightCrawler(CrawlerConfig(timeout=30))
        page = crawler.crawl("https://spa-app.example.com")
    """

    def __init__(self, config: CrawlerConfig | None = None) -> None:
        self._config = config or CrawlerConfig()
        self._ensure_playwright()

    @staticmethod
    def _ensure_playwright() -> None:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "playwright is required for PlaywrightCrawler. "
                "Install: uv add playwright && playwright install chromium"
            ) from exc

    def crawl(
        self,
        url: str,
        proxy: ProxyDict | None = None,
    ) -> CrawledPage:
        from playwright.sync_api import sync_playwright

        cfg = self._config
        start = time.perf_counter()
        fetched_at = datetime.now(UTC).isoformat()

        launch_kwargs: dict = {"headless": True}
        if proxy:
            http_proxy = proxy.get("http") or proxy.get("https", "")
            if http_proxy:
                launch_kwargs["proxy"] = {"server": http_proxy}

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(**launch_kwargs)
                context = browser.new_context(
                    user_agent=cfg.user_agent,
                    java_script_enabled=True,
                )
                page = context.new_page()
                page.set_default_timeout(cfg.timeout * 1000)

                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=cfg.timeout * 1000,
                )
                # Wait briefly for dynamic content
                page.wait_for_timeout(1500)

                status = response.status if response else 0
                final_url = page.url
                html = page.content()
                latency_ms = (time.perf_counter() - start) * 1000

                browser.close()

            # Re-use the stdlib HTML parser for consistent extraction
            from discovery.crawler import _build_meta, _PageParser

            parser = _PageParser(final_url, max_links=cfg.max_links)
            parser.feed(html)
            raw_text = parser.text
            meta = _build_meta(parser, raw_text, cfg.extract_tech)

            return CrawledPage(
                url=url,
                final_url=final_url,
                status_code=status,
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
            logger.warning("Playwright crawl failed %s: %s", url, exc)
            return CrawledPage(
                url=url,
                final_url=url,
                status_code=0,
                title="",
                text_content="",
                meta=ExtractedMeta(),
                links=[],
                crawled_at=fetched_at,
                latency_ms=latency_ms,
                success=False,
                error=str(exc),
            )

    def crawl_many(
        self,
        urls: list[str],
        max_workers: int = 3,  # Playwright is heavy; default lower
        proxy_provider: BaseProxyProvider | None = None,
    ) -> list[CrawledPage]:
        """Crawl multiple URLs using a thread pool (each thread gets its own browser)."""
        if not urls:
            return []

        results: dict[str, CrawledPage] = {}

        def _fetch(url: str) -> tuple[str, CrawledPage]:
            proxy = proxy_provider.get_proxy() if proxy_provider else None
            page = self.crawl(url, proxy=proxy)
            if not page.success and proxy_provider and proxy:
                proxy_provider.report_failure(proxy, page.error or "")
                new_proxy = proxy_provider.rotate()
                page = self.crawl(url, proxy=new_proxy)
            return url, page

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(max_workers, len(urls)),
            thread_name_prefix="pw_crawler",
        ) as pool:
            futures = {pool.submit(_fetch, url): url for url in urls}
            for future in concurrent.futures.as_completed(futures):
                orig_url = futures[future]
                try:
                    key, page = future.result()
                    results[key] = page
                except Exception as exc:
                    logger.error("Playwright error for %s: %s", orig_url, exc)
                    results[orig_url] = CrawledPage(
                        url=orig_url,
                        final_url=orig_url,
                        status_code=0,
                        title="",
                        text_content="",
                        meta=ExtractedMeta(),
                        links=[],
                        crawled_at=datetime.now(UTC).isoformat(),
                        latency_ms=0.0,
                        success=False,
                        error=str(exc),
                    )

        return [results[u] for u in urls if u in results]
