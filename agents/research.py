from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from agents.base import BaseAgent
from agents.factory import register_agent

logger = logging.getLogger(__name__)


class CompanyProfile(BaseModel):
    """Rich company profile synthesised by LLM from multiple crawled pages."""

    company_name: str = Field(description="Best-fit company name")
    description: str = Field(
        description="2–3 sentence company description covering product, market, and scale"
    )
    estimated_employees: str = Field(
        default="unknown",
        description="Employee range estimate, e.g. '100-500', 'startup <50'",
    )
    headquarters: str = Field(
        default="unknown",
        description="HQ location if mentioned",
    )
    founded_year: str = Field(
        default="unknown",
        description="Year founded if mentioned",
    )
    tech_stack: list[str] = Field(
        description="Technologies confirmed in use (from page text)",
    )
    key_products: list[str] = Field(
        description="Main products or services offered",
    )
    customers_or_verticals: list[str] = Field(
        description="Known customer types or industry verticals served",
    )
    recent_news: list[str] = Field(
        description="Recent events: funding, launches, hires, expansions",
    )
    pain_points: list[str] = Field(
        description="Engineering/tech challenges visible from job posts or blog",
    )
    outsourcing_readiness: str = Field(
        description=(
            "Assessment of outsourcing likelihood: 'high' | 'medium' | 'low'. "
            "Based on signals like rapid hiring, tech complexity, contract roles."
        )
    )
    pitch_angle: str = Field(
        description=(
            "Strongest 1-sentence pitch tailored specifically to this company's "
            "current situation (reference their actual signals)"
        )
    )
    recommended_services: list[str] = Field(
        description="Top 2-3 services most likely to resonate with this company",
    )
    key_people_mentioned: list[str] = Field(
        description="Names and titles of people mentioned (executives, founders, authors)",
    )


@register_agent("research")
class ResearchAgent(BaseAgent):
    """
    Deep company research agent.

    Synthesises multiple crawled pages (homepage, careers, about, blog, etc.)
    into a rich ``CompanyProfile`` using the configured LLM.

    Falls back to a minimal profile from rule-based signal extraction if
    the LLM is unavailable.

    Args:
        llm:      Any ``BaseLLM`` — use a larger model for better quality.
        bus:      Optional ``EventBus``.
        session:  Optional ``Session``.
    """

    name = "research"
    required_model_role = "lead_scorer"  # uses the same model as scoring by default

    def run(self, *args: Any, **kwargs: Any) -> CompanyProfile:
        """Run research on ``domain`` using ``pages`` (list of CrawledPage)."""
        domain: str = args[0] if args else str(kwargs.get("domain", ""))
        pages: list = (args[1] if len(args) > 1 else None) or kwargs.get("pages", [])
        return self.research(domain, pages)

    def research(self, domain: str, pages: list) -> CompanyProfile:
        """
        Synthesise crawled pages into a ``CompanyProfile``.

        Args:
            domain: The company domain, e.g. ``"acmecorp.com"``.
            pages:  List of ``CrawledPage`` objects for this company.

        Returns:
            A ``CompanyProfile`` (never None).
        """
        if not pages:
            return self._empty_profile(domain)

        # Aggregate text from all pages (cap total to ~4000 tokens worth)
        text_block = _aggregate_page_text(pages, max_chars=8000)
        prompt = _build_research_prompt(domain, text_block)

        result = self._safe_invoke(prompt, CompanyProfile, fallback=None)
        if result is None:
            logger.warning("Research LLM call failed for %s — using minimal profile", domain)
            return self._fallback_profile(domain, pages)

        logger.info(
            "Research complete: %s | employees=%s | outsourcing=%s",
            result.company_name,
            result.estimated_employees,
            result.outsourcing_readiness,
        )
        return result

    def _empty_profile(self, domain: str) -> CompanyProfile:
        return CompanyProfile(
            company_name=domain,
            description="No pages available for research.",
            tech_stack=[],
            key_products=[],
            customers_or_verticals=[],
            recent_news=[],
            pain_points=[],
            outsourcing_readiness="unknown",
            pitch_angle="",
            recommended_services=[],
            key_people_mentioned=[],
        )

    def _fallback_profile(self, domain: str, pages: list) -> CompanyProfile:
        """Rule-based minimal profile when LLM is unavailable."""
        all_tech: set[str] = set()
        all_emails: list[str] = []
        for page in pages:
            if hasattr(page, "meta"):
                all_tech.update(page.meta.tech_signals or [])
                all_emails.extend(page.meta.emails or [])
        title = pages[0].title if pages else domain
        return CompanyProfile(
            company_name=title or domain,
            description=f"Company at {domain}. Research requires LLM.",
            tech_stack=sorted(all_tech)[:10],
            key_products=[],
            customers_or_verticals=[],
            recent_news=[],
            pain_points=[],
            outsourcing_readiness="unknown",
            pitch_angle="",
            recommended_services=[],
            key_people_mentioned=[],
        )


def _aggregate_page_text(pages: list, max_chars: int = 8000) -> str:
    """Combine text from all pages, labelled by URL, up to ``max_chars``."""
    parts: list[str] = []
    budget = max_chars
    for page in pages:
        if not page.success or not page.text_content:
            continue
        label = f"[PAGE: {page.url}]"
        chunk = page.text_content[: min(budget, 2000)]
        parts.append(f"{label}\n{chunk}")
        budget -= len(chunk)
        if budget <= 0:
            break
    return "\n\n".join(parts)


def _build_research_prompt(domain: str, text_block: str) -> str:
    return f"""You are a B2B sales intelligence analyst researching a company for software outsourcing outreach.

Company domain: {domain}

Web pages content:
{text_block}

Based ONLY on the above content (do not hallucinate facts not present in the text):
1. Build a complete company profile.
2. Identify engineering challenges and outsourcing signals.
3. Recommend the strongest pitch angle for software development services.

Be specific. Quote actual technologies, team names, or events you see in the text.
If something is not mentioned, say "unknown" or leave the list empty.
""".strip()
