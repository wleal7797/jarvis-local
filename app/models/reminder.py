"""Recordatorios (Etapa 13): JARVIS avisa en voz alta y en pantalla a la hora indicada."""

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin


class Reminder(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "reminders"
    __table_args__ = (
        # El vigilante busca "pendientes que ya vencieron": índice sólo sobre los pendientes.
        Index("ix_reminders_pending_due", "due_at", postgresql_where="fired_at IS NULL"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    text: Mapped[str]
    due_at: Mapped[datetime]
    fired_at: Mapped[datetime | None]
    # True si avisó tarde (JARVIS estaba apagado a esa hora).
    late: Mapped[bool] = mapped_column(default=False, server_default="false")
