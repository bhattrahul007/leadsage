from __future__ import annotations

from typing import Generic, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, model: Type[T], db: Session) -> None:
        self._model = model
        self._db = db

    def add(self, instance: T) -> T:
        self._db.add(instance)
        self._db.flush()
        return instance

    def get(self, pk) -> T | None:
        return self._db.get(self._model, pk)

    def list(self, **filters) -> list[T]:
        stmt = select(self._model)
        for attr, val in filters.items():
            stmt = stmt.where(getattr(self._model, attr) == val)
        return list(self._db.execute(stmt).scalars().all())

    def delete(self, instance: T) -> None:
        self._db.delete(instance)
        self._db.flush()

    def update(self, instance: T, **kwargs) -> T:
        for k, v in kwargs.items():
            setattr(instance, k, v)
        self._db.flush()
        return instance
