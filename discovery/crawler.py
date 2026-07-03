from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
import json
import logging
import re
import time
from urllib.parse import urljoin, urlparse

import requests

from common.retry import RetryConfig, retry_with_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tech keyword list for signal detection
# ---------------------------------------------------------------------------

_TECH_KEYWORDS: frozenset[str] = frozenset(
    {
        # Cloud / Infra
        "kubernetes",
        "k8s",
        "docker",
        "terraform",
        "ansible",
        "aws",
        "gcp",
        "azure",
        "cloudflare",
        "digitalocean",
        "heroku",
        # Backend
        "python",
        "golang",
        "go",
        "rust",
        "java",
        "node.js",
        "nodejs",
        "ruby on rails",
        "rails",
        "django",
        "fastapi",
        "flask",
        "spring",
        ".net",
        "c#",
        "php",
        "scala",
        "kotlin",
        # Frontend
        "react",
        "vue",
        "angular",
        "next.js",
        "nextjs",
        "nuxt",
        "typescript",
        "graphql",
        "tailwind",
        # Data
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "elasticsearch",
        "snowflake",
        "databricks",
        "airflow",
        "spark",
        "kafka",
        "dbt",
        "bigquery",
        "redshift",
        # AI / ML
        "pytorch",
        "tensorflow",
        "openai",
        "langchain",
        "llm",
        "machine learning",
        "mlops",
        "hugging face",
        # DevOps / CI
        "github actions",
        "gitlab",
        "jenkins",
        "argocd",
        "helm",
        "prometheus",
        "grafana",
        "datadog",
        "sentry",
        "pagerduty",
        # Mobile
        "react native",
        "flutter",
        "swift",
        "android",
        "ios",
    }
)

_SOCIAL_PATTERNS: dict[str, re.Pattern] = {
    "linkedin": re.compile(r"linkedin\.com/(?:company|in)/[^\"'\s>]+", re.I),
    "github": re.compile(r"github\.com/[^\"'\s>]+", re.I),
    "twitter": re.compile(r"(?:twitter|x)\.com/[^\"'\s>]+", re.I),
    "crunchbase": re.compile(r"crunchbase\.com/organization/[^\"'\s>]+", re.I),
    "angellist": re.compile(r"angel\.co/company/[^\"'\s>]+", re.I),
}

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s\-])?(?:\(?\d{2,4}\)?[\s\-])?\d{3,4}[\s\-]\d{3,4}")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class CrawlerConfig:
    """
    Configuration for ``WebCrawler``.

    Attributes
    ----------
    timeout:             HTTP timeout in seconds.
    max_content_bytes:   Max response body size to process (default 500 KB).
    user_agent:          Browser-like User-Agent header.
    max_links:           Maximum links to extract per page.
    extract_tech:        Whether to run tech keyword detection.
    domain_delay_seconds: Seconds to wait between requests to the same domain.
    retries:             Retry attempts on transient failures.
    retry_backoff:       Base backoff seconds.
    """

    timeout: int = 15
    max_content_bytes: int = 500_000
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
    max_links: int = 50
    extract_tech: bool = True
    domain_delay_seconds: float = 0.0
    retries: int = 1
    retry_backoff: float = 1.0


# ---------------------------------------------------------------------------
# Extracted data models
# ---------------------------------------------------------------------------


@dataclass
class ExtractedMeta:
    """
    All structured metadata extracted from a crawled page.
    Every field has a sensible default — never None.
    """

    title: str = ""
    description: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    og_type: str = ""
    og_site_name: str = ""
    canonical_url: str = ""
    json_ld: list[dict] = field(default_factory=list)
    social_links: dict[str, str] = field(default_factory=dict)
    emails: list[str] = field(default_factory=list)
    phone_numbers: list[str] = field(default_factory=list)
    tech_signals: list[str] = field(default_factory=list)


@dataclass
class CrawledPage:
    """
    The full result of crawling one URL.

    ``success=True``  — ``text_content``, ``meta``, ``links`` are populated.
    ``success=False`` — ``error`` explains what went wrong; other fields empty.
    """

    url: str  # Original URL requested
    final_url: str  # URL after any redirects
    status_code: int  # HTTP status code (0 on network error)
    title: str  # Page <title>
    text_content: str  # Cleaned plain text, no HTML
    meta: ExtractedMeta
    links: list[str]  # Absolute URLs found on the page
    crawled_at: str  # ISO 8601 UTC
    latency_ms: float
    success: bool
    error: str | None = None

    @property
    def word_count(self) -> int:
        return len(self.text_content.split())

    @property
    def domain(self) -> str:
        try:
            return urlparse(self.final_url).netloc.removeprefix("www.")
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------------


class _PageParser(HTMLParser):
    """
    Single-pass HTML parser — extracts text, meta tags, links, and JSON-LD.
    Never raises; errors are silently dropped so crawling never fails on
    malformed HTML.
    """

    def __init__(self, base_url: str, max_links: int) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_links = max_links

        self.title: str = ""
        self.description: str = ""
        self.og: dict[str, str] = {}
        self.canonical: str = ""
        self.json_ld: list[dict] = []
        self.links: list[str] = []

        self._text_parts: list[str] = []
        self._in_script: bool = False
        self._in_style: bool = False
        self._in_title: bool = False
        self._in_json_ld: bool = False
        self._json_buf: list[str] = []

    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs_list) -> None:
        attrs = dict(attrs_list)
        t = tag.lower()

        if t == "title":
            self._in_title = True

        elif t in ("script", "style"):
            script_type = attrs.get("type", "")
            if script_type == "application/ld+json":
                self._in_json_ld = True
                self._json_buf = []
            else:
                self._in_script = t == "script"
                self._in_style = t == "style"

        elif t == "meta":
            name = attrs.get("name", "").lower()
            prop = attrs.get("property", "").lower()
            content = attrs.get("content", "")
            if name == "description":
                self.description = content
            elif prop.startswith("og:"):
                self.og[prop[3:]] = content

        elif t == "link":
            if attrs.get("rel") == "canonical":
                self.canonical = attrs.get("href", "")

        elif t == "a":
            href = attrs.get("href", "").strip()
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                abs_url = urljoin(self.base_url, href)
                if abs_url.startswith("http") and len(self.links) < self.max_links:
                    self.links.append(abs_url)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = False
        elif t in ("script", "style"):
            if self._in_json_ld:
                self._flush_json_ld()
            self._in_script = False
            self._in_style = False
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_buf.append(data)
        elif self._in_title:
            self.title += data
        elif not self._in_script and not self._in_style:
            stripped = data.strip()
            if stripped:
                self._text_parts.append(stripped)

    # ------------------------------------------------------------------

    def _flush_json_ld(self) -> None:
        raw = "".join(self._json_buf).strip()
        if not raw:
            return
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                self.json_ld.extend(parsed)
            elif isinstance(parsed, dict):
                self.json_ld.append(parsed)
        except Exception:
            pass

    @property
    def text(self) -> str:
        return " ".join(self._text_parts)


# ---------------------------------------------------------------------------
# WebCrawler
# ---------------------------------------------------------------------------


class WebCrawler:
    """
    Fetches and parses web pages, returning structured ``CrawledPage`` objects.

    Example
    -------
    ::

        crawler = WebCrawler(CrawlerConfig(timeout=10, extract_tech=True))

        page   = crawler.crawl("https://acmecorp.com")
        pages  = crawler.crawl_many(["https://acmecorp.com", "https://betainc.com"])
    """

    def __init__(self, config: CrawlerConfig | None = None) -> None:
        self.config = config or CrawlerConfig()
        self._domain_last_hit: dict[str, float] = {}

        retry_cfg = RetryConfig(
            max_attempts=self.config.retries + 1,
            backoff=self.config.retry_backoff,
            jitter="equal",
            exceptions=(
                requests.ConnectionError,
                requests.Timeout,
                requests.HTTPError,
            ),
            predicate=lambda e: (
                not isinstance(e, requests.HTTPError)
                or getattr(getattr(e, "response", None), "status_code", 0) >= 500
            ),
        )
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.config.user_agent})

        @retry_with_config(retry_cfg)
        def _fetch(url: str) -> requests.Response:
            resp = self._session.get(
                url,
                timeout=self.config.timeout,
                stream=True,
                allow_redirects=True,
            )
            resp.raise_for_status()
            return resp

        self._fetch = _fetch

    # ------------------------------------------------------------------

    def crawl(self, url: str) -> CrawledPage:
        """Fetch and parse a single URL. Always returns a CrawledPage."""
        start = time.perf_counter()
        fetched_at = datetime.now(UTC).isoformat()
        cfg = self.config

        # Per-domain rate limiting
        self._apply_rate_limit(url)

        try:
            resp = self._fetch(url)
            latency_ms = (time.perf_counter() - start) * 1000

            # Read up to max_content_bytes
            raw = b""
            for chunk in resp.iter_content(chunk_size=8192):
                raw += chunk
                if len(raw) >= cfg.max_content_bytes:
                    break

            html = raw.decode("utf-8", errors="replace")
            final_url = resp.url
            status = resp.status_code

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
            logger.warning("Crawl failed for %s: %s", url, exc)
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
        max_workers: int = 10,
    ) -> list[CrawledPage]:
        """
        Crawl multiple URLs concurrently.

        Results are returned in the same order as ``urls``.
        Failed crawls are included (``success=False``) so callers always
        get a 1:1 mapping between input URLs and output pages.
        """
        if not urls:
            return []

        results: dict[str, CrawledPage] = {}

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="crawler_worker",
        ) as pool:
            future_to_url = {pool.submit(self.crawl, url): url for url in urls}
            for future in concurrent.futures.as_completed(future_to_url):
                orig_url = future_to_url[future]
                try:
                    results[orig_url] = future.result()
                except Exception as exc:
                    logger.error("Unexpected crawl error for %s: %s", orig_url, exc)
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

        # Preserve input order
        return [results[u] for u in urls]

    # ------------------------------------------------------------------

    def _apply_rate_limit(self, url: str) -> None:
        delay = self.config.domain_delay_seconds
        if delay <= 0:
            return
        try:
            domain = urlparse(url).netloc
        except Exception:
            return
        last = self._domain_last_hit.get(domain, 0.0)
        elapsed = time.perf_counter() - last
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._domain_last_hit[domain] = time.perf_counter()


# ---------------------------------------------------------------------------
# Meta extraction helpers
# ---------------------------------------------------------------------------


def _build_meta(
    parser: _PageParser,
    text: str,
    extract_tech: bool,
) -> ExtractedMeta:
    og = parser.og
    html_blob = text.lower()

    social_links: dict[str, str] = {}
    for platform, pattern in _SOCIAL_PATTERNS.items():
        match = pattern.search(text)
        if match:
            social_links[platform] = "https://" + match.group(0).lstrip("/")

    emails = list(dict.fromkeys(_EMAIL_RE.findall(text)))[:10]
    phones = list(dict.fromkeys(_PHONE_RE.findall(text)))[:5]

    tech_signals: list[str] = []
    if extract_tech:
        tech_signals = sorted({kw for kw in _TECH_KEYWORDS if kw in html_blob})

    return ExtractedMeta(
        title=parser.title.strip(),
        description=parser.description,
        og_title=og.get("title", ""),
        og_description=og.get("description", ""),
        og_image=og.get("image", ""),
        og_type=og.get("type", ""),
        og_site_name=og.get("site_name", ""),
        canonical_url=parser.canonical,
        json_ld=parser.json_ld,
        social_links=social_links,
        emails=emails,
        phone_numbers=phones,
        tech_signals=tech_signals,
    )
