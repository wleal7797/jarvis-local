"""Cola de tareas de ingesta guardada en PostgreSQL (sin Redis)."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select

from app.models import IngestionJob, Source
from app.repositories.base_repository import BaseRepository


class JobRepository(BaseRepository[IngestionJob]):
    model = IngestionJob

    async def claim_next(self) -> IngestionJob | None:
        """Toma la tarea más antigua en cola y la marca como "running".

        `FOR UPDATE SKIP LOCKED`: si hubiera varios workers, cada uno toma una tarea
        distinta sin bloquearse entre sí. Es lo que permite usar PostgreSQL como cola.
        """
        job = await self.session.scalar(
            select(IngestionJob)
            .where(IngestionJob.status == "queued")
            .order_by(IngestionJob.created_at, IngestionJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is not None:
            job.status = "running"
            job.started_at = datetime.now(UTC)
            await self.session.flush()
        return job

    async def recent(
        self, owner_user_id: int, limit: int = 30
    ) -> Sequence[tuple[IngestionJob, Source]]:
        stmt = (
            select(IngestionJob, Source)
            .join(Source)
            .where((Source.is_personal.is_(False)) | (Source.owner_user_id == owner_user_id))
            .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
            .limit(limit)
        )
        return [(row.IngestionJob, row.Source) for row in (await self.session.execute(stmt)).all()]

    async def requeue_stuck(self) -> int:
        """Al arrancar el worker, las tareas que quedaron "running" vuelven a la cola."""
        stuck = (
            await self.session.scalars(select(IngestionJob).where(IngestionJob.status == "running"))
        ).all()
        for job in stuck:
            job.status = "queued"
        await self.session.flush()
        return len(stuck)
