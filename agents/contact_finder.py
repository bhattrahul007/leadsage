from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from agents.base import BaseAgent
from agents.factory import register_agent
from common.schemas.lead_output import DecisionMaker

logger = logging.getLogger(__name__)


class _ExtractedContact(BaseModel):
    """One contact extracted by the LLM from page text."""

    name: str = Field(description="Full name if visible, else empty string")
    title: str = Field(description="Job title or role")
    email: str | None = Field(default=None, description="Email if explicitly found")
    linkedin_url: str | None = Field(default=None, description="LinkedIn profile URL if found")
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="How confident you are this is a real decision-maker (0–1)",
    )


class _ContactExtractionResult(BaseModel):
    """Batch of contacts extracted from one page."""

    contacts: list[_ExtractedContact] = Field(
        description="All decision-makers and key contacts found on this page",
    )
    email_domain_pattern: str = Field(
        default="",
        description=(
            "Most likely email pattern for this company, "
            "e.g. 'firstname.lastname@domain.com' or 'firstname@domain.com'"
        ),
    )


@register_agent("contact_finder")
class ContactFinderAgent(BaseAgent):
    """
    Extracts decision-maker contacts from crawled page text using LLM + regex.

    Strategy:
    1. Regex pre-pass to collect emails, LinkedIn URLs, GitHub URLs from page.
    2. LLM structured extraction of names, titles, and any contacts from text.
    3. Merge results and de-duplicate.
    4. Infer likely email pattern from confirmed emails + domain.

    Args:
        llm:     LLM for structured extraction.
        bus:     Optional EventBus.
        session: Optional Session.
    """

    name = "contact_finder"
    required_model_role = "contact_finder"

    # Regex patterns for fast pre-extraction
    _EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    _LINKEDIN_RE = re.compile(r"linkedin\.com/in/[\w\-]+", re.I)
    _GITHUB_RE = re.compile(r"github\.com/[\w\-]+(?!/)", re.I)

    def run(self, domain: str, pages: list, **kwargs: Any) -> list[DecisionMaker]:
        """Find contacts across all provided pages for ``domain``."""
        return self.find_contacts(domain, pages)

    def find_contacts(self, domain: str, pages: list) -> list[DecisionMaker]:
        """
        Extract decision-maker contacts from crawled pages.

        Args:
            domain: Company domain (used to filter relevant emails).
            pages:  List of ``CrawledPage`` objects.

        Returns:
            De-duplicated list of ``DecisionMaker`` objects.
        """
        all_contacts: list[DecisionMaker] = []
        seen_titles: set[str] = set()

        for page in pages:
            if not page.success or not page.text_content:
                continue
            contacts = self._extract_from_page(page, domain)
            for c in contacts:
                key = c.title.lower()
                if key not in seen_titles:
                    all_contacts.append(c)
                    seen_titles.add(key)

        # Sort by confidence descending
        all_contacts.sort(key=lambda c: -c.confidence)
        return all_contacts[:10]  # cap at 10 per company

    def _extract_from_page(self, page, domain: str) -> list[DecisionMaker]:
        """Extract contacts from a single page using LLM + regex."""
        text = page.text_content or ""

        # Fast regex pass
        regex_emails = _filter_domain_emails(self._EMAIL_RE.findall(text), domain)
        regex_linkedins = ["https://" + m for m in self._LINKEDIN_RE.findall(text)]

        # LLM extraction (only if enough text)
        llm_contacts: list[_ExtractedContact] = []
        if len(text) > 100:
            result = self._safe_invoke(
                _build_extraction_prompt(domain, text[:3000]),
                _ContactExtractionResult,
            )
            if result:
                llm_contacts = result.contacts or []

        # Merge into DecisionMaker list
        dms: list[DecisionMaker] = []
        for c in llm_contacts:
            if not c.title:
                continue
            dm = DecisionMaker(
                name=c.name or None,
                title=c.title,
                email=c.email or (regex_emails[0] if regex_emails else None),
                linkedin_url=c.linkedin_url or (regex_linkedins[0] if regex_linkedins else None),
                confidence=c.confidence,
            )
            dms.append(dm)

        # If LLM found nothing but regex found contacts, create minimal DMs
        if not dms and (regex_emails or regex_linkedins):
            dms.append(
                DecisionMaker(
                    title="Contact",
                    email=regex_emails[0] if regex_emails else None,
                    linkedin_url=regex_linkedins[0] if regex_linkedins else None,
                    confidence=0.3,
                )
            )

        return dms


def _filter_domain_emails(emails: list[str], domain: str) -> list[str]:
    """Keep only emails that match the company domain."""
    base_domain = domain.removeprefix("www.")
    return [e for e in emails if base_domain in e.lower()]


def _build_extraction_prompt(domain: str, text: str) -> str:
    return f"""You are extracting decision-maker contacts from a company webpage.

Company domain: {domain}

Page text (first 3000 chars):
{text}

Extract all executives, founders, and engineering decision-makers you can identify.
Include: name (if visible), title, email (if found), LinkedIn URL (if found).
Assign confidence 0.9 if explicitly named, 0.5 if inferred from context.
Only extract contacts relevant to software/tech decisions (CTO, VP Eng, CISO, CPO, Founder, etc.).
""".strip()
