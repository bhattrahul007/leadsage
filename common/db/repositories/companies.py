from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import CompanyModel, DecisionMakerModel
from common.db.repositories.base import BaseRepository


class CompanyRepository(BaseRepository[CompanyModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(CompanyModel, db)

    def upsert(self, domain: str, **fields) -> CompanyModel:
        record = self.get(domain)
        if record:
            # Merge list signals rather than overwrite
            for list_field in ("tech_stack", "industry_tags"):
                incoming = fields.pop(list_field, None)
                if incoming:
                    existing = set(getattr(record, list_field) or [])
                    setattr(record, list_field, sorted(existing | set(incoming)))
            for k, v in fields.items():
                if v is not None:
                    setattr(record, k, v)
            record.updated_at = datetime.now(timezone.utc)
            self._db.flush()
            return record
        record = CompanyModel(domain=domain, **fields)
        return self.add(record)

    def search_by_industry(self, industry_tag: str) -> list[CompanyModel]:
        stmt = select(CompanyModel).where(CompanyModel.industry_tags.contains([industry_tag]))
        return list(self._db.execute(stmt).scalars().all())

    def search_by_tech(self, tech: str) -> list[CompanyModel]:
        stmt = select(CompanyModel).where(CompanyModel.tech_stack.contains([tech]))
        return list(self._db.execute(stmt).scalars().all())

    def get_yc_companies(self, batch: str | None = None) -> list[CompanyModel]:
        stmt = select(CompanyModel).where(CompanyModel.is_yc_company.is_(True))
        if batch:
            stmt = stmt.where(CompanyModel.yc_batch == batch)
        return list(self._db.execute(stmt).scalars().all())


class DecisionMakerRepository(BaseRepository[DecisionMakerModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(DecisionMakerModel, db)

    def upsert(
        self,
        domain: str,
        title: str,
        email: str | None = None,
        linkedin_url: str | None = None,
        **fields,
    ) -> DecisionMakerModel:
        stmt = select(DecisionMakerModel).where(DecisionMakerModel.domain == domain)
        if email:
            stmt = stmt.where(DecisionMakerModel.email == email)
        elif linkedin_url:
            stmt = stmt.where(DecisionMakerModel.linkedin_url == linkedin_url)
        else:
            stmt = stmt.where(DecisionMakerModel.title == title)

        record = self._db.execute(stmt).scalar_one_or_none()
        if record:
            for k, v in fields.items():
                setattr(record, k, v)
            self._db.flush()
            return record

        record = DecisionMakerModel(
            domain=domain,
            title=title,
            email=email,
            linkedin_url=linkedin_url,
            **fields,
        )
        return self.add(record)

    def list_by_domain(self, domain: str) -> list[DecisionMakerModel]:
        stmt = (
            select(DecisionMakerModel)
            .where(DecisionMakerModel.domain == domain)
            .order_by(DecisionMakerModel.confidence.desc())
        )
        return list(self._db.execute(stmt).scalars().all())
