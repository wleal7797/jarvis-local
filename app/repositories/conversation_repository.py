"""Conversaciones y sus mensajes."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Conversation, Message
from app.repositories.base_repository import BaseRepository


class ConversationRepository(BaseRepository[Conversation]):
    model = Conversation

    async def get_for_user(self, conversation_id: int, user_id: int) -> Conversation | None:
        """Sólo devuelve la conversación si pertenece a ese usuario."""
        return await self.session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )

    async def list_for_user(self, user_id: int, limit: int = 50) -> Sequence[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
            .limit(limit)
        )
        return (await self.session.scalars(stmt)).all()

    async def messages(self, conversation_id: int) -> Sequence[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        return (await self.session.scalars(stmt)).all()

    async def recent_messages(self, conversation_id: int, limit: int) -> list[Message]:
        """Los últimos `limit` mensajes, en orden cronológico."""
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_(("user", "assistant")),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        newest_first = (await self.session.scalars(stmt)).all()
        return list(reversed(newest_first))

    async def touch(self, conversation: Conversation) -> None:
        """Marca la conversación como recién usada (para ordenarlas)."""
        conversation.updated_at = datetime.now(UTC)
        await self.session.flush()
