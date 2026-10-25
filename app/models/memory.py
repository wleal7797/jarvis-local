"""Memoria de largo plazo: datos que JARVIS recuerda de cada usuario."""

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, SmallInteger, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import EMBEDDING_DIM, Base, CreatedAtMixin, IdMixin

if TYPE_CHECKING:
    from app.models.user import User


class Memory(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (CheckConstraint("importance BETWEEN 1 AND 5", name="importance"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(HALFVEC(EMBEDDING_DIM))
    importance: Mapped[int] = mapped_column(SmallInteger, server_default=text("3"))
    source_message_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("messages.id", ondelete="SET NULL")
    )
    last_used_at: Mapped[datetime | None]

    user: Mapped["User"] = relationship(back_populates="memories", lazy="raise")


Index(
    "ix_memories_embedding_hnsw",
    Memory.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "halfvec_cosine_ops"},
)
