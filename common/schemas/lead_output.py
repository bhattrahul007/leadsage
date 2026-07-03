from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class LeadTier(StrEnum):
    """Lead quality tier: HOT (≥ hot_threshold), WARM (≥ warm_threshold), COLD (below)."""

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class ContactInfo(BaseModel):
    """Contact details extracted from crawled pages and search metadata."""

    emails: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    linkedin_url: str | None = None
    github_url: str | None = None
    twitter_url: str | None = None
    crunchbase_url: str | None = None
    angellist_url: str | None = None
    website: str | None = None


class DecisionMaker(BaseModel):
    """A potential buyer persona identified at this company."""

    title: str = Field(description="Job title, e.g. 'CTO', 'VP Engineering'")
    name: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence this person is a real decision maker (0–1)",
    )


class ScoreBreakdown(BaseModel):
    """Decomposition of the rule-based ICP relevance score."""

    technology: float = 0.0  # tech stack match
    hiring: float = 0.0  # hiring signal strength
    profile: float = 0.0  # industry / size / location match
    composite: float = 0.0  # weighted final


class OutreachSuggestion(BaseModel):
    """
    A concrete, personalised outreach angle for this specific company.

    Channels: linkedin (default), email, call, any.
    """

    channel: Literal["email", "linkedin", "call", "any"] = "linkedin"
    subject_line: str | None = Field(
        default=None,
        description="Email subject or LinkedIn InMail headline (≤10 words)",
    )
    opening_hook: str = Field(
        default="",
        description="First sentence — personalised attention-grabber",
    )
    key_talking_points: list[str] = Field(
        default_factory=list,
        description="3–5 specific value propositions for this company",
    )
    personalization_hooks: list[str] = Field(
        default_factory=list,
        description="Company-specific details to reference for rapport",
    )


class ScoredLead(BaseModel):
    """
    Complete, scored, enriched company lead — the pipeline's final output.

    JSON-serialisable. Use ``to_dict()`` for export or ``model_dump()``
    for Pydantic-native serialisation.
    """

    domain: str
    company_name: str
    source_url: str

    icp_relevance_score: float = Field(ge=0.0, le=1.0)
    lead_tier: LeadTier
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)

    contact_info: ContactInfo = Field(default_factory=ContactInfo)
    decision_makers: list[DecisionMaker] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    hiring_signals: list[str] = Field(default_factory=list)
    outsourcing_signals: list[str] = Field(default_factory=list)
    business_events: list[str] = Field(default_factory=list)
    industry_signals: list[str] = Field(default_factory=list)

    company_summary: str = Field(
        default="",
        description="1–2 sentence description of what this company does",
    )
    why_this_lead: str = Field(
        default="",
        description="Why this company is a good ICP match — LLM rationale",
    )
    outreach_suggestions: list[OutreachSuggestion] = Field(default_factory=list)

    evidence: list[str] = Field(
        default_factory=list,
        description="Text snippets from the crawled page that support the score",
    )

    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_enriched_lead(
        cls,
        lead,  # EnrichedLead
        tier: LeadTier,
        company_summary: str = "",
        why_this_lead: str = "",
        outreach_suggestions: list[OutreachSuggestion] | None = None,
        decision_makers: list[DecisionMaker] | None = None,
    ) -> ScoredLead:
        """
        Construct a ``ScoredLead`` from an ``EnrichedLead`` + LLM enrichment.

        The ``EnrichedLead`` supplies all rule-based fields;
        the LLM enrichment supplies tier, summaries, and outreach.
        """
        contact = ContactInfo(
            emails=getattr(lead, "emails", []),
            phone_numbers=getattr(lead, "phone_numbers", []),
            linkedin_url=getattr(lead, "linkedin_url", None),
            github_url=getattr(lead, "github_url", None),
            twitter_url=getattr(lead, "twitter_url", None),
            crunchbase_url=getattr(lead, "crunchbase_url", None),
            angellist_url=getattr(lead, "angellist_url", None),
            website=lead.source_url,
        )

        return cls(
            domain=lead.domain,
            company_name=lead.company_name,
            source_url=lead.source_url,
            icp_relevance_score=lead.icp_relevance_score,
            lead_tier=tier,
            score_breakdown=ScoreBreakdown(
                technology=lead.score.technology,
                hiring=lead.score.hiring,
                profile=lead.score.profile,
                composite=lead.score.composite,
            ),
            contact_info=contact,
            decision_makers=decision_makers or [],
            tech_stack=lead.tech_stack,
            hiring_signals=lead.hiring_signals,
            outsourcing_signals=lead.outsourcing_signals,
            business_events=lead.business_events,
            industry_signals=lead.industry_signals,
            company_summary=company_summary,
            why_this_lead=why_this_lead,
            outreach_suggestions=outreach_suggestions or [],
            evidence=lead.evidence,
        )

    def to_dict(self) -> dict:
        """Return a JSON-safe dict (delegates to Pydantic's model_dump)."""
        return self.model_dump()

    def __repr__(self) -> str:
        return (
            f"<ScoredLead [{self.lead_tier.value.upper()}] "
            f"{self.domain!r} score={self.icp_relevance_score:.2f}>"
        )
