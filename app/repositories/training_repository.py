"""Calificaciones de respuestas y ejemplos de entrenamiento."""

from collections.abc import Sequence

from sqlalchemy import delete, func, select

from app.models import Feedback, TrainingDataset, TrainingExample
from app.repositories.base_repository import BaseRepository


class TrainingRepository(BaseRepository[Feedback]):
    model = Feedback

    async def feedback_for_message(self, message_id: int) -> Feedback | None:
        return await self.session.scalar(select(Feedback).where(Feedback.message_id == message_id))

    async def ratings_for(self, message_ids: Sequence[int]) -> dict[int, int]:
        if not message_ids:
            return {}
        rows = await self.session.execute(
            select(Feedback.message_id, Feedback.rating).where(Feedback.message_id.in_(message_ids))
        )
        return {row.message_id: row.rating for row in rows}

    async def dataset(self, name: str, description: str, personal: bool) -> TrainingDataset:
        """El dataset con ese nombre; lo crea si no existe."""
        found = await self.session.scalar(
            select(TrainingDataset).where(TrainingDataset.name == name)
        )
        if found is not None:
            return found
        dataset = TrainingDataset(
            name=name, description=description, contains_personal_data=personal
        )
        self.session.add(dataset)
        await self.session.flush()
        return dataset

    async def replace_examples(self, feedback_id: int, examples: Sequence[TrainingExample]) -> None:
        await self.session.execute(
            delete(TrainingExample).where(TrainingExample.feedback_id == feedback_id)
        )
        self.session.add_all(examples)
        await self.session.flush()

    async def count_examples(self, dataset_id: int) -> int:
        return (
            await self.session.scalar(
                select(func.count()).where(TrainingExample.dataset_id == dataset_id)
            )
            or 0
        )
