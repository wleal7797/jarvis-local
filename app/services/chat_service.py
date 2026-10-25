"""Orquesta una respuesta de JARVIS.

Flujo de cada pregunta:
1. Guarda el mensaje del usuario (crea la conversación si es nueva).
2. Arma el prompt con el historial reciente.
3. Pide la respuesta al modelo y la va entregando pedazo a pedazo.
4. Al terminar, guarda la respuesta con sus estadísticas.

Usa su propia sesión de base de datos (no la de la petición) porque la respuesta
sigue generándose después de que el controlador devolvió el `StreamingResponse`.
"""

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Conversation, Message
from app.repositories import ConversationRepository, ModelVersionRepository
from app.services.llm import LLMError, LLMProvider
from app.services.prompt_builder import build_messages

logger = logging.getLogger(__name__)

HISTORY_MESSAGES = 20
TITLE_LENGTH = 60
MODEL_UNAVAILABLE = "JARVIS no pudo responder: el modelo no está disponible."

ChatEvent = dict[str, Any]


class ConversationNotFoundError(LookupError):
    pass


def make_title(text: str) -> str:
    title = " ".join(text.split())
    return title if len(title) <= TITLE_LENGTH else title[: TITLE_LENGTH - 1].rstrip() + "…"


class ChatService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm: LLMProvider,
        model: str,
    ) -> None:
        self._session_factory = session_factory
        self._llm = llm
        self._model = model

    async def ensure_conversation(self, user_id: int, conversation_id: int) -> None:
        """Lanza `ConversationNotFoundError` si no existe o no es de ese usuario."""
        async with self._session_factory() as session:
            if await ConversationRepository(session).get_for_user(conversation_id, user_id) is None:
                raise ConversationNotFoundError(conversation_id)

    async def answer(
        self, user_id: int, text: str, conversation_id: int | None = None
    ) -> AsyncIterator[ChatEvent]:
        started = time.perf_counter()

        # 1. Guardar la pregunta.
        async with self._session_factory() as session:
            repo = ConversationRepository(session)
            conversation = await self._get_or_create(repo, user_id, conversation_id, text)
            history = await repo.recent_messages(conversation.id, HISTORY_MESSAGES)
            question = await repo.add(
                Message(conversation_id=conversation.id, role="user", content=text)
            )
            await repo.touch(conversation)
            await session.commit()
            conversation_id = conversation.id

        yield {"type": "start", "conversation_id": conversation_id, "message_id": question.id}

        # 2 y 3. Generar la respuesta en streaming.
        parts: list[str] = []
        stats = None
        try:
            async for chunk in self._llm.chat_stream(
                build_messages(history, text), model=self._model
            ):
                if chunk.content:
                    parts.append(chunk.content)
                    yield {"type": "token", "content": chunk.content}
                if chunk.done:
                    stats = chunk
        except LLMError as exc:
            logger.error("El modelo falló", extra={"error": str(exc)})
            yield {"type": "error", "message": MODEL_UNAVAILABLE}
            return

        # 4. Guardar la respuesta.
        latency_ms = int((time.perf_counter() - started) * 1000)
        async with self._session_factory() as session:
            model_version = await ModelVersionRepository(session).get_by_tag(self._model)
            reply = await ConversationRepository(session).add(
                Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content="".join(parts).strip(),
                    model_version_id=model_version.id if model_version else None,
                    tokens_in=stats.tokens_in if stats else None,
                    tokens_out=stats.tokens_out if stats else None,
                    latency_ms=latency_ms,
                )
            )
            await session.commit()

        logger.info(
            "respuesta generada",
            extra={
                "conversation_id": conversation_id,
                "latency_ms": latency_ms,
                "tokens_out": stats.tokens_out if stats else None,
                "tokens_per_second": stats.tokens_per_second if stats else None,
            },
        )
        yield {
            "type": "end",
            "message_id": reply.id,
            "latency_ms": latency_ms,
            "tokens_in": reply.tokens_in,
            "tokens_out": reply.tokens_out,
            "tokens_per_second": stats.tokens_per_second if stats else None,
        }

    async def _get_or_create(
        self, repo: ConversationRepository, user_id: int, conversation_id: int | None, text: str
    ) -> Conversation:
        if conversation_id is not None:
            conversation = await repo.get_for_user(conversation_id, user_id)
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            return conversation
        return await repo.add(Conversation(user_id=user_id, title=make_title(text)))
