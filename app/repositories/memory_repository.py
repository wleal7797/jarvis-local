"""Acceso a los recuerdos de cada usuario (tabla `memories`)."""

from collections.abc import Sequence

from sqlalchemy import select

from app.models import Memory
from app.repositories.base_repository import BaseRepository


class MemoryRepository(BaseRepository[Memory]):
    model = Memory

    async def list_for_user(self, user_id: int) -> Sequence[Memory]:
        """Los más importantes primero; a igual importancia, los más nuevos."""
        stmt = (
            select(Memory)
            .where(Memory.user_id == user_id)
            .order_by(Memory.importance.desc(), Memory.created_at.desc(), Memory.id.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def get_for_user(self, memory_id: int, user_id: int) -> Memory | None:
        memory = await self.session.get(Memory, memory_id)
        return memory if memory is not None and memory.user_id == user_id else None

    async def exists_for(self, user_id: int) -> bool:
        return (
            await self.session.scalar(select(Memory.id).where(Memory.user_id == user_id).limit(1))
        ) is not None

    async def nearest(
        self, user_id: int, embedding: list[float], k: int, min_similarity: float
    ) -> Sequence[Memory]:
        distance = Memory.embedding.cosine_distance(embedding)
        stmt = (
            select(Memory)
            .where(Memory.user_id == user_id, distance <= 1 - min_similarity)
            .order_by(distance)
            .limit(k)
        )
        return (await self.session.scalars(stmt)).all()

    async def most_similar(
        self, user_id: int, embedding: list[float]
    ) -> tuple[Memory, float] | None:
        """El recuerdo más parecido en significado y su similitud (0 a 1)."""
        distance = Memory.embedding.cosine_distance(embedding)
        stmt = (
            select(Memory, distance.label("distance"))
            .where(Memory.user_id == user_id)
            .order_by(distance)
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        return (row.Memory, 1.0 - row.distance) if row else None
