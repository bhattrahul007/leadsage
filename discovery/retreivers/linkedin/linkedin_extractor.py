from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discovery.crawler import CrawledPage

_SIZE_RE = re.compile(r"(\d[\d,]*)\s*(?:to|-)\s*(\d[\d,]*)\s*employees", re.IGNORECASE)
_FOUNDED_RE = re.compile(r"founded\s*[:\-]?\s*(\d{4})", re.IGNORECASE)
_HQ_RE = re.compile(r"headquartered?\s+(?:in\s+)?([A-Z][^,\n]{2,40})", re.IGNORECASE)


@dataclass
class LinkedInProfile:
    """Structured data extracted from a LinkedIn company page."""

    company_name: str = ""
    tagline: str = ""
    industry: str = ""
    employee_count: str = ""
    specialties: list[str] = field(default_factory=list)
    founded: str = ""
    headquarters: str = ""


class LinkedInExtractor:
    """
    Post-crawl enricher for LinkedIn company pages.

    Not a search provider — pass a ``CrawledPage`` whose URL contains
    ``linkedin.com/company`` to ``extract()``.

    Example::

        extractor = LinkedInExtractor()
        profile = extractor.extract(crawled_page)
        if profile:
            lead.company_summary = profile.tagline
    """

    def extract(self, page: "CrawledPage") -> LinkedInProfile | None:
        if not page.success:
            return None
        if "linkedin.com/company" not in (page.final_url or page.url):
            return None

        text = page.text_content or ""
        name = (page.title or "").split("|")[0].strip()

        return LinkedInProfile(
            company_name=name,
            tagline=(page.meta.description or "")[:250],
            industry=self._extract_industry(text),
            employee_count=self._extract_size(text),
            founded=self._extract_founded(text),
            headquarters=self._extract_hq(text),
            specialties=self._extract_specialties(text),
        )

    def _extract_industry(self, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if re.search(r"\b(industry|sector)\b", stripped, re.IGNORECASE):
                return stripped[:80]
        return ""

    def _extract_size(self, text: str) -> str:
        m = _SIZE_RE.search(text)
        return m.group(0) if m else ""

    def _extract_founded(self, text: str) -> str:
        m = _FOUNDED_RE.search(text)
        return m.group(1) if m else ""

    def _extract_hq(self, text: str) -> str:
        m = _HQ_RE.search(text)
        return m.group(1).strip() if m else ""

    def _extract_specialties(self, text: str) -> list[str]:
        m = re.search(r"specialt(?:y|ies)[:\s]+([^\n]{10,200})", text, re.IGNORECASE)
        if not m:
            return []
        raw = m.group(1)
        return [s.strip() for s in re.split(r"[,·|]", raw) if s.strip()][:10]
