from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import LeadModel, OutreachSuggestionModel
from common.db.repositories.base import BaseRepository


class LeadRepository(BaseRepository[LeadModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(LeadModel, db)

    def upsert(self, session_id: str, domain: str, **fields) -> LeadModel:
        stmt = select(LeadModel).where(
            LeadModel.session_id == session_id,
            LeadModel.domain == domain,
        )
        record = self._db.execute(stmt).scalar_one_or_none()
        if record:
            for k, v in fields.items():
                setattr(record, k, v)
            self._db.flush()
            return record

        record = LeadModel(session_id=session_id, domain=domain, **fields)
        return self.add(record)

    def list_by_session(self, session_id: str, tier: str | None = None) -> list[LeadModel]:
        stmt = select(LeadModel).where(LeadModel.session_id == session_id)
        if tier:
            stmt = stmt.where(LeadModel.lead_tier == tier)
        stmt = stmt.order_by(LeadModel.icp_relevance_score.desc())
        return list(self._db.execute(stmt).scalars().all())

    def top_by_session(self, session_id: str, n: int = 20) -> list[LeadModel]:
        stmt = (
            select(LeadModel)
            .where(LeadModel.session_id == session_id)
            .order_by(LeadModel.icp_relevance_score.desc())
            .limit(n)
        )
        return list(self._db.execute(stmt).scalars().all())

    def add_outreach(
        self,
        lead_id: int,
        session_id: str,
        domain: str,
        channel: str = "linkedin",
        subject_line: str | None = None,
        opening_hook: str | None = None,
        key_talking_points: list | None = None,
        personalization: list | None = None,
    ) -> OutreachSuggestionModel:
        record = OutreachSuggestionModel(
            lead_id=lead_id,
            session_id=session_id,
            domain=domain,
            channel=channel,
            subject_line=subject_line,
            opening_hook=opening_hook,
            key_talking_points=key_talking_points or [],
            personalization=personalization or [],
        )
        self._db.add(record)
        self._db.flush()
        return record