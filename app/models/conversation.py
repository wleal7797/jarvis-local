"""Conversaciones, mensajes, fuentes citadas y calificaciones."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, SmallInteger, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin, check_in

if TYPE_CHECKING:
    from app.models.user import User

CHANNELS = ("text", "voice")
MESSAGE_ROLES = ("system", "user", "assistant", "tool")


class Conversation(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (check_in("channel", CHANNELS, "channel"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None]
    channel: Mapped[str] = mapped_column(server_default=text("'text'"))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="conversations", lazy="raise")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
        lazy="raise",
    )


Index("ix_conversations_user_recent", Conversation.user_id, Conversation.updated_at.desc())


class Message(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        check_in("role", MESSAGE_ROLES, "role"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str]
    content: Mapped[str]
    model_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    audio_path: Mapped[str | None]
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    latency_ms: Mapped[int | None]

    conversation: Mapped[Conversation] = relationship(back_populates="messages", lazy="raise")
    feedback: Mapped["Feedback | None"] = relationship(back_populates="message", lazy="raise")


class MessageSource(Base):
    """Qué fragmentos de conocimiento usó JARVIS para escribir una respuesta."""

    __tablename__ = "message_sources"

    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(SmallInteger)
    score: Mapped[float | None]


class Feedback(IdMixin, CreatedAtMixin, Base):
    """Calificación 👍 / 👎 de una respuesta, con corrección opcional."""

    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("rating IN (-1, 1)", name="rating"),)

    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[int] = mapped_column(SmallInteger)
    correction: Mapped[str | None]
    use_for_training: Mapped[bool] = mapped_column(server_default=text("false"))

    message: Mapped[Message] = relationship(back_populates="feedback", lazy="raise")
