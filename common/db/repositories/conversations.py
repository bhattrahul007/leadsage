from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import ConversationMessageModel
from common.db.repositories.base import BaseRepository


class ConversationRepository(BaseRepository[ConversationMessageModel]):
    def __init__(self, db: Session) -> None:
        super().__init__(ConversationMessageModel, db)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_name: str | None = None,
        model_name: str | None = None,
        tokens: int = 0,
    ) -> ConversationMessageModel:
        record = ConversationMessageModel(
            session_id=session_id,
            role=role,
            content=content,
            agent_name=agent_name,
            model_name=model_name,
            tokens=tokens,
        )
        return self.add(record)

    def get_history(self, session_id: str, last_n: int | None = None) -> list[ConversationMessageModel]:
        stmt = (
            select(ConversationMessageModel)
            .where(ConversationMessageModel.session_id == session_id)
            .order_by(ConversationMessageModel.created_at.asc())
        )
        if last_n:
            stmt = stmt.order_by(ConversationMessageModel.created_at.desc()).limit(last_n)
            results = list(self._db.execute(stmt).scalars().all())
            return list(reversed(results))
        return list(self._db.execute(stmt).scalars().all())

    def get_context_string(self, session_id: str, last_n: int = 10) -> str:
        history = self.get_history(session_id, last_n=last_n)
        lines = []
        for msg in history:
            prefix = {"user": "Human", "assistant": "Assistant", "system": "System"}.get(msg.role, msg.role)
            lines.append(f"{prefix}: {msg.content}")
        return "\n".join(lines)