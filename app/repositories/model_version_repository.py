"""Versiones de modelo registradas (base o ajustadas con LoRA)."""

from sqlalchemy import select, update

from app.models import ModelVersion
from app.repositories.base_repository import BaseRepository


class ModelVersionRepository(BaseRepository[ModelVersion]):
    model = ModelVersion

    async def get_by_tag(self, ollama_tag: str) -> ModelVersion | None:
        return await self.session.scalar(
            select(ModelVersion).where(ModelVersion.ollama_tag == ollama_tag)
        )

    async def get_active(self) -> ModelVersion | None:
        return await self.session.scalar(select(ModelVersion).where(ModelVersion.is_active))

    async def set_active(self, model_version: ModelVersion) -> None:
        """Activa un modelo y desactiva el anterior (sólo puede haber uno)."""
        await self.session.execute(
            update(ModelVersion).where(ModelVersion.is_active).values(is_active=False)
        )
        await self.session.flush()
        model_version.is_active = True
        await self.session.flush()
