from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.pipeline_service import RunResult

logger = logging.getLogger(__name__)


class PersistenceService:
    """
    Saves a ``RunResult`` to the database via ORM repositories.

    Designed to be independent of pipeline logic — can be called
    from CLI, API, or a background worker after the run completes.
    """

    def save(self, run: "RunResult") -> bool:
        import common.db as db

        if not db.is_available():
            return False
        try:
            self._persist(run)
            return True
        except Exception as exc:
            logger.warning("DB persist failed: %s", exc)
            return False

    def _persist(self, run: "RunResult") -> None:
        import common.db as db
        from common.db.repositories import (
            SessionRepository,
            LeadRepository,
            CompanyRepository,
            DecisionMakerRepository,
            PipelineMetricRepository,
        )

        with db.db_session() as orm_db:
            SessionRepository(orm_db).upsert_or_create(run.session_id, run.query, run.tier_counts)
            lead_repo = LeadRepository(orm_db)
            company_repo = CompanyRepository(orm_db)
            dm_repo = DecisionMakerRepository(orm_db)

            for lead in run.scored_leads:
                company_repo.upsert(
                    domain=lead.domain,
                    company_name=lead.company_name,
                    tech_stack=lead.tech_stack,
                    industry_tags=lead.industry_signals,
                    linkedin_url=lead.contact_info.linkedin_url,
                    github_url=lead.contact_info.github_url,
                    twitter_url=lead.contact_info.twitter_url,
                    crunchbase_url=lead.contact_info.crunchbase_url,
                    website=lead.source_url,
                )
                lead_repo.upsert(
                    session_id=run.session_id,
                    domain=lead.domain,
                    company_name=lead.company_name,
                    lead_tier=lead.lead_tier.value,
                    icp_relevance_score=lead.icp_relevance_score,
                    tech_score=lead.score_breakdown.technology,
                    hiring_score=lead.score_breakdown.hiring,
                    profile_score=lead.score_breakdown.profile,
                    tech_stack=lead.tech_stack,
                    hiring_signals=lead.hiring_signals,
                    outsourcing_signals=lead.outsourcing_signals,
                    business_events=lead.business_events,
                    industry_signals=lead.industry_signals,
                    company_summary=lead.company_summary,
                    why_this_lead=lead.why_this_lead,
                    source_url=lead.source_url,
                    evidence=lead.evidence,
                )
                for dm in lead.decision_makers:
                    try:
                        dm_repo.upsert(
                            domain=lead.domain,
                            title=dm.title,
                            full_name=dm.name,
                            email=dm.email,
                            linkedin_url=dm.linkedin_url,
                            confidence=dm.confidence,
                            session_id=run.session_id,
                        )
                    except Exception:
                        pass

            metric_repo = PipelineMetricRepository(orm_db)
            for metric in run.pipeline_result.stage_metrics:
                metric_repo.log_stage(
                    session_id=run.session_id,
                    stage=metric.stage,
                    items_in=metric.items_in,
                    items_out=metric.items_out,
                    error_count=metric.error_count,
                    latency_ms=metric.latency_ms,
                )
            orm_db.commit()
