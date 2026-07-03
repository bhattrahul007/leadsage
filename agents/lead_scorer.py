from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from agents.base import BaseAgent
from agents.factory import register_agent
from common.llm.base import BaseLLM
from common.schemas.icp_request import IcpDiscoveryQuery
from common.schemas.lead_output import (
    ContactInfo,
    DecisionMaker,
    LeadTier,
    OutreachSuggestion,
    ScoredLead,
)

logger = logging.getLogger(__name__)


class _LLMEnrichment(BaseModel):
    """Structured output the LLM fills in for each lead."""

    tier: Literal["hot", "warm", "cold"] = Field(
        description=(
            "Lead quality. hot = strong ICP match and high outsourcing signals, "
            "warm = moderate match, cold = weak match"
        )
    )
    company_summary: str = Field(
        description="1–2 sentences describing what this company does and its scale"
    )
    why_reach_out: str = Field(
        description=(
            "1–2 sentences explaining why this company is likely to need "
            "software development outsourcing or staff augmentation right now"
        )
    )
    channel: Literal["email", "linkedin", "call", "any"] = Field(
        default="linkedin",
        description="Best outreach channel for this company type",
    )
    subject_line: str = Field(
        description="Email subject or LinkedIn InMail headline — max 10 words, specific to this company"
    )
    opening_hook: str = Field(
        description=(
            "First sentence of the outreach — personalised to this company's "
            "specific signals (their tech, hiring, recent events)"
        )
    )
    talking_points: list[str] = Field(
        description=(
            "3–5 specific value propositions tailored to this company's needs. "
            "Reference their actual tech stack, hiring patterns, or business events."
        )
    )
    personalization_hooks: list[str] = Field(
        description=(
            "2–3 company-specific details to mention to build credibility "
            "(e.g. 'noticed you're scaling your Kubernetes team')"
        )
    )
    decision_maker_titles: list[str] = Field(
        description="Best 2–3 job titles to target at this specific company",
    )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@register_agent("lead_scorer")
class LeadScorerAgent(BaseAgent):
    """
    Enriches ``EnrichedLead`` objects with LLM scoring and outreach copy.

    Args:
        llm:            Any ``BaseLLM`` implementation.
        icp:            The ``IcpDiscoveryQuery`` providing context.
        hot_threshold:  Score ≥ this → HOT tier.
        warm_threshold: Score ≥ this → WARM tier (else COLD).
        llm_enabled:    Set False to use rule-based tier only (faster, no LLM).
    """

    name = "lead_scorer"
    required_model_role = "lead_scorer"

    def __init__(
        self,
        llm: BaseLLM,
        icp: IcpDiscoveryQuery,
        hot_threshold: float = 0.65,
        warm_threshold: float = 0.35,
        llm_enabled: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(llm=llm, **kwargs)
        self._icp = icp
        self._hot_t = hot_threshold
        self._warm_t = warm_threshold
        self._llm_enabled = llm_enabled

    def run(self, *args: Any, **kwargs: Any) -> list[ScoredLead]:
        """Run scoring on a list of enriched leads. Used by AgentFactory."""
        enriched_leads = args[0] if args else kwargs.get("enriched_leads", [])
        max_workers = int(kwargs.get("max_workers", 5))
        return self.score_many(enriched_leads, max_workers=max_workers)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, enriched_lead) -> ScoredLead:
        """
        Score one ``EnrichedLead`` → ``ScoredLead``.

        If the LLM call fails the lead still gets a rule-based tier and
        empty outreach fields rather than being dropped.

        Args:
            enriched_lead: An ``EnrichedLead`` from ``LeadEnricher``.

        Returns:
            A fully populated ``ScoredLead``.
        """
        # Rule-based tier as the safe default
        tier = _rule_tier(enriched_lead.icp_relevance_score, self._hot_t, self._warm_t)

        decision_makers = _build_decision_makers(enriched_lead, self._icp)
        company_summary = ""
        why_reach_out = ""
        outreach: list[OutreachSuggestion] = []

        if self._llm_enabled:
            try:
                enrichment = cast(
                    _LLMEnrichment,
                    self.llm.invoke_structured(
                        _build_prompt(enriched_lead, self._icp), _LLMEnrichment
                    ),
                )
                tier = LeadTier(enrichment.tier)
                company_summary = enrichment.company_summary
                why_reach_out = enrichment.why_reach_out
                outreach = [
                    OutreachSuggestion(
                        channel=enrichment.channel,
                        subject_line=enrichment.subject_line,
                        opening_hook=enrichment.opening_hook,
                        key_talking_points=enrichment.talking_points,
                        personalization_hooks=enrichment.personalization_hooks,
                    )
                ]
                # Merge LLM-suggested decision-maker titles
                existing_titles = {dm.title.lower() for dm in decision_makers}
                for title in enrichment.decision_maker_titles:
                    if title.lower() not in existing_titles:
                        decision_makers.append(DecisionMaker(title=title, confidence=0.7))
                        existing_titles.add(title.lower())

            except Exception as exc:
                logger.warning(
                    "LLM scoring failed for %s (%s: %s) — rule-based tier kept.",
                    enriched_lead.domain,
                    type(exc).__name__,
                    exc,
                )

        # Publish event
        from common.events.events import LeadScored

        self._publish(
            LeadScored(
                session_id=self.session_id,
                domain=enriched_lead.domain,
                company_name=enriched_lead.company_name,
                tier=tier.value,
                icp_score=enriched_lead.icp_relevance_score,
                llm_model=self.llm.model_name,
            )
        )

        return ScoredLead.from_enriched_lead(
            lead=enriched_lead,
            tier=tier,
            company_summary=company_summary,
            why_this_lead=why_reach_out,
            outreach_suggestions=outreach,
            decision_makers=decision_makers,
        )

    def score_many(
        self,
        enriched_leads: list,
        max_workers: int = 5,
    ) -> list[ScoredLead]:
        """
        Score a list of leads concurrently.

        Args:
            enriched_leads: List of ``EnrichedLead`` objects.
            max_workers:    Thread-pool size. Each thread calls the LLM
                            sequentially, so keep this ≤ your model's
                            concurrency limit.

        Returns:
            List of ``ScoredLead``, sorted by ``icp_relevance_score`` desc.
        """
        if not enriched_leads:
            return []

        results: list[ScoredLead] = []

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="lead_scorer",
        ) as pool:
            future_map = {pool.submit(self.score, lead): lead for lead in enriched_leads}
            for future in concurrent.futures.as_completed(future_map):
                lead = future_map[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.error(
                        "Unexpected scoring error for %s: %s",
                        getattr(lead, "domain", "?"),
                        exc,
                    )

        results.sort(key=lambda r: -r.icp_relevance_score)
        return results


def _rule_tier(score: float, hot_t: float, warm_t: float) -> LeadTier:
    if score >= hot_t:
        return LeadTier.HOT
    if score >= warm_t:
        return LeadTier.WARM
    return LeadTier.COLD


def _build_contact(lead) -> ContactInfo:
    """Build ``ContactInfo`` from the enriched lead's extracted fields."""
    return ContactInfo(
        emails=getattr(lead, "emails", []),
        phone_numbers=getattr(lead, "phone_numbers", []),
        linkedin_url=getattr(lead, "linkedin_url", None),
        github_url=getattr(lead, "github_url", None),
        twitter_url=getattr(lead, "twitter_url", None),
        crunchbase_url=getattr(lead, "crunchbase_url", None),
        angellist_url=getattr(lead, "angellist_url", None),
        website=lead.source_url,
    )


def _build_decision_makers(lead, icp: IcpDiscoveryQuery) -> list[DecisionMaker]:
    """Convert ``decision_maker_hints`` into typed ``DecisionMaker`` objects."""
    icp_titles_lower = {t.lower() for t in icp.buyer_persona.titles}
    dms: list[DecisionMaker] = []
    for hint in lead.decision_maker_hints:
        confidence = 0.9 if hint.lower() in icp_titles_lower else 0.5
        dms.append(DecisionMaker(title=hint, confidence=confidence))
    return dms


def _build_prompt(lead, icp: IcpDiscoveryQuery) -> str:
    """Construct the full scoring prompt from lead signals + ICP context."""
    icp_lines = []
    if icp.target_company.industries:
        icp_lines.append(f"Industries: {', '.join(icp.target_company.industries)}")
    if icp.locations.countries:
        icp_lines.append(f"Countries: {', '.join(icp.locations.countries)}")
    if icp.technologies.required:
        icp_lines.append(f"Required tech: {', '.join(icp.technologies.required)}")
    if icp.technologies.preferred:
        icp_lines.append(f"Preferred tech: {', '.join(icp.technologies.preferred)}")
    if icp.buyer_persona.titles:
        icp_lines.append(f"Target titles: {', '.join(icp.buyer_persona.titles)}")
    if icp.engagement.models:
        icp_lines.append(f"Engagement models: {', '.join(icp.engagement.models)}")
    if icp.outsource.engagement_models:
        icp_lines.append(f"Outsourcing models: {', '.join(icp.outsource.engagement_models)}")
    icp_block = "\n".join(icp_lines) or "(no ICP constraints specified)"

    signal_lines = []
    if lead.tech_stack:
        signal_lines.append(f"Tech stack detected: {', '.join(lead.tech_stack[:10])}")
    if lead.hiring_signals:
        signal_lines.append(f"Hiring: {', '.join(lead.hiring_signals[:6])}")
    if lead.outsourcing_signals:
        signal_lines.append(f"Outsourcing signals: {', '.join(lead.outsourcing_signals[:5])}")
    if lead.business_events:
        signal_lines.append(f"Business events: {', '.join(lead.business_events[:5])}")
    if lead.industry_signals:
        signal_lines.append(f"Industry signals: {', '.join(lead.industry_signals[:4])}")
    if lead.decision_maker_hints:
        signal_lines.append(f"Decision-maker mentions: {', '.join(lead.decision_maker_hints[:4])}")
    if lead.emails:
        signal_lines.append(f"Emails found: {', '.join(lead.emails[:3])}")
    signal_block = "\n".join(signal_lines) or "(no signals detected)"

    evidence_block = ""
    if lead.evidence:
        snippets = "\n".join(f"  • {e}" for e in lead.evidence[:3])
        evidence_block = f"\nPage evidence:\n{snippets}"

    return f"""You are a B2B sales intelligence analyst evaluating a prospect for software outsourcing / staff augmentation services.

=== ICP (What We're Looking For) ===
{icp_block}

=== Lead Being Evaluated ===
Company : {lead.company_name}
Domain  : {lead.domain}
Source  : {lead.source_url}
Rule-based ICP score: {lead.icp_relevance_score:.2f} / 1.00

Signals found:
{signal_block}{evidence_block}

=== Task ===
1. Classify this lead as hot / warm / cold based on how well it matches the ICP and shows outsourcing need.
2. Summarise what this company does (1–2 sentences, factual).
3. Explain WHY we should reach out now (specific signals, not generic).
4. Write a personalised outreach message opening and talking points — use THEIR specific signals (tech stack, hiring roles, events), not generic templates.

Be specific. If you don't have enough signal to justify a hot rating, give warm or cold.
""".strip()
