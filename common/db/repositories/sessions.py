from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import SessionModel
from common.db.repositories.base import BaseRepository


class SessionRepository(BaseRepository[SessionModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(SessionModel, db)

    def create(self, session_id: str, query: str, parsed_icp: dict | None = None) -> SessionModel:
        record = SessionModel(
            id=session_id or str(uuid.uuid4()),
            query=query,
            parsed_icp=parsed_icp or {},
            status="created",
        )
        return self.add(record)

    def get_by_id(self, session_id: str) -> SessionModel | None:
        return self.get(session_id)

    def mark_running(self, session_id: str) -> SessionModel | None:
        record = self.get(session_id)
        if record:
            record.status = "running"
            record.updated_at = datetime.now(timezone.utc)
            self._db.flush()
        return record

    def mark_completed(
        self,
        session_id: str,
        total_leads: int = 0,
        hot_count: int = 0,
        warm_count: int = 0,
        cold_count: int = 0,
        pipeline_ms: float = 0.0,
    ) -> SessionModel | None:
        record = self.get(session_id)
        if record:
            record.status = "completed"
            record.completed_at = datetime.now(timezone.utc)
            record.updated_at = datetime.now(timezone.utc)
            record.total_leads = total_leads
            record.hot_count = hot_count
            record.warm_count = warm_count
            record.cold_count = cold_count
            record.pipeline_ms = pipeline_ms
            self._db.flush()
        return record

    def mark_failed(self, session_id: str, error: str) -> SessionModel | None:
        record = self.get(session_id)
        if record:
            record.status = "failed"
            record.error = error
            record.updated_at = datetime.now(timezone.utc)
            self._db.flush()
        return record

    def upsert_or_create(self, session_id: str, query: str, tier_counts: dict) -> SessionModel:
        record = self.get(session_id)
        if record:
            record.status = "completed"
            record.total_leads = sum(tier_counts.values())
            record.hot_count = tier_counts.get("hot", 0)
            record.warm_count = tier_counts.get("warm", 0)
            record.cold_count = tier_counts.get("cold", 0)
            record.updated_at = datetime.now(timezone.utc)
            self._db.flush()
            return record
        return self.create(session_id, query)

    def list_recent(self, limit: int = 20) -> list[SessionModel]:
        stmt = select(SessionModel).order_by(SessionModel.created_at.desc()).limit(limit)
        return list(self._db.execute(stmt).scalars().all())