"""Operaciones comunes de acceso a datos para cualquier entidad."""

from collections.abc import Sequence
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Base


class BaseRepository[ModelT: Base]:
    model: ClassVar[type[Base]]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, entity_id: int) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()  # asigna el id sin confirmar todavía la transacción
        return entity

    async def list(self, limit: int = 50, offset: int = 0) -> Sequence[ModelT]:
        stmt = select(self.model).order_by(self.model.id).limit(limit).offset(offset)
        return (await self.session.scalars(stmt)).all()

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()
