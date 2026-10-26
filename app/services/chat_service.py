"""Orquesta una respuesta de JARVIS.

Flujo de cada pregunta:
1. Guarda el mensaje del usuario (crea la conversación si es nueva).
2. Busca en los documentos los fragmentos que mejor responden la pregunta (RAG).
3. Arma el prompt con el historial reciente y esos fragmentos numerados.
4. Pide la respuesta al modelo y la va entregando pedazo a pedazo.
5. Al terminar, guarda la respuesta, sus estadísticas y las fuentes consultadas.

Usa su propia sesión de base de datos (no la de la petición) porque la respuesta
sigue generándose después de que el controlador devolvió el `StreamingResponse`.
"""

import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Conversation, Message, MessageSource
from app.repositories import ConversationRepository, ModelVersionRepository
from app.services.embedding_service import EmbeddingError
from app.services.llm import LLMError, LLMProvider
from app.services.prompt_builder import CONTEXT_TOKEN_BUDGET, build_messages, fit_context
from app.services.retrieval_service import RetrievedChunk

logger = logging.getLogger(__name__)

HISTORY_MESSAGES = 20
# Por voz se leen ~2 fragmentos en vez de 3 (cada 250 tokens cuestan ~1 s en la GTX 1650 Ti).
# Con 900 (1 fragmento) era ~30 % más rápido pero falló respuestas que necesitaban 2.
VOICE_CONTEXT_TOKENS = 1100
# Por voz, una o dos frases: cada token son ~25 ms en la GPU y respuestas largas cansan al oído.
VOICE_MAX_TOKENS = 200
TITLE_LENGTH = 60
MODEL_UNAVAILABLE = "JARVIS no pudo responder: el modelo no está disponible."
CITATION = re.compile(r"\[(\d{1,2})\]")

ChatEvent = dict[str, Any]


class Retriever(Protocol):
    async def search(
        self, query: str, owner_user_id: int | None = None
    ) -> list[RetrievedChunk]: ...


RetrieverFactory = Callable[[AsyncSession], Retriever]


class ConversationNotFoundError(LookupError):
    pass


def make_title(text: str) -> str:
    title = " ".join(text.split())
    return title if len(title) <= TITLE_LENGTH else title[: TITLE_LENGTH - 1].rstrip() + "…"


_WORD = re.compile(r"[a-záéíóúñü0-9]+", re.IGNORECASE)
# Saludos y frases cortas no necesitan documentos (leerlos cuesta ~6 s en esta GPU).
MIN_CONTENT_WORDS_FOR_DOCUMENTS = 4


def is_small_talk(text: str) -> bool:
    """ "Gracias, Jarvis", "¿Cómo estás?", "¿Qué hora es?" → sí. Preguntas con contenido → no."""
    words = [w for w in _WORD.findall(text.lower()) if len(w) > 2 and w != "jarvis"]
    return len(words) < MIN_CONTENT_WORDS_FOR_DOCUMENTS


# Por voz sólo se buscan documentos para preguntas: "Recuérdame comprar leche" o
# "Me gusta el café" no necesitan buscar (buscar + leer cuesta ~8 s en esta GPU).
_ASKS = re.compile(
    r"\?|^\W*(?:jarvis\W+)?(?:qu[eé]|qui[eé]n|cu[aá]l|c[oó]mo|d[oó]nde|cu[aá]ndo|cu[aá]nt|"
    r"por\s+qu[eé]|expl[ií](?:c|qu)|d[ií]game|dime|cu[eé]nt|h[aá]bl|busc|sabe|sabes)",
    re.IGNORECASE,
)


def voice_needs_documents(text: str) -> bool:
    """Por voz: ¿vale la pena buscar en los documentos? Sólo preguntas con contenido."""
    return not is_small_talk(text) and bool(_ASKS.search(text))


def cited_numbers(answer: str, available: int) -> list[int]:
    """Números de fuente que el modelo citó de verdad (ignora los inventados)."""
    found = {int(n) for n in CITATION.findall(answer)}
    return sorted(n for n in found if 1 <= n <= available)


def source_payload(chunks: Sequence[RetrievedChunk]) -> list[dict[str, Any]]:
    return [
        {
            "n": number,
            "chunk_id": chunk.chunk_id,
            "title": chunk.title,
            "section": chunk.section,
            "uri": chunk.uri,
            "similarity": chunk.similarity,
        }
        for number, chunk in enumerate(chunks, start=1)
    ]


class ChatService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm: LLMProvider,
        model: str,
        retriever_factory: RetrieverFactory | None = None,
        voice_context_tokens: int = VOICE_CONTEXT_TOKENS,
        voice_max_tokens: int = VOICE_MAX_TOKENS,
    ) -> None:
        self._session_factory = session_factory
        self._llm = llm
        self._model = model
        self._retriever_factory = retriever_factory
        self._voice_context_tokens = voice_context_tokens
        self._voice_max_tokens = voice_max_tokens

    async def ensure_conversation(self, user_id: int, conversation_id: int) -> None:
        """Lanza `ConversationNotFoundError` si no existe o no es de ese usuario."""
        async with self._session_factory() as session:
            if await ConversationRepository(session).get_for_user(conversation_id, user_id) is None:
                raise ConversationNotFoundError(conversation_id)

    async def answer(
        self,
        user_id: int,
        text: str,
        conversation_id: int | None = None,
        *,
        voice: bool = False,
    ) -> AsyncIterator[ChatEvent]:
        """`voice=True`: conversación hablada, se lee menos contexto para responder antes."""
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

        # 2. Buscar en los documentos.
        # Por voz: menos contexto, y nada de documentos para charla corta (responde antes).
        retrieval_started = time.perf_counter()
        if voice and not voice_needs_documents(text):
            context = []
        else:
            if self._retriever_factory is not None:
                # Buscar y leer documentos tarda: se avisa para mostrarlo (y decirlo por voz).
                yield {"type": "searching"}
            budget = self._voice_context_tokens if voice else CONTEXT_TOKEN_BUDGET
            context = await self._retrieve(text, user_id, budget)
        retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)
        first_token_ms: int | None = None
        if context:
            yield {"type": "sources", "sources": source_payload(context)}

        # 3 y 4. Generar la respuesta en streaming.
        parts: list[str] = []
        stats = None
        try:
            async for chunk in self._llm.chat_stream(
                build_messages(history, text, context, spoken=voice),
                model=self._model,
                options={"num_predict": self._voice_max_tokens} if voice else None,
            ):
                if chunk.content:
                    if first_token_ms is None:
                        first_token_ms = int((time.perf_counter() - started) * 1000)
                    parts.append(chunk.content)
                    yield {"type": "token", "content": chunk.content}
                if chunk.done:
                    stats = chunk
        except LLMError as exc:
            logger.error("El modelo falló", extra={"error": str(exc)})
            yield {"type": "error", "message": MODEL_UNAVAILABLE}
            return

        # 5. Guardar la respuesta y sus fuentes.
        answer_text = "".join(parts).strip()
        latency_ms = int((time.perf_counter() - started) * 1000)
        async with self._session_factory() as session:
            model_version = await ModelVersionRepository(session).get_by_tag(self._model)
            reply = await ConversationRepository(session).add(
                Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer_text,
                    model_version_id=model_version.id if model_version else None,
                    tokens_in=stats.tokens_in if stats else None,
                    tokens_out=stats.tokens_out if stats else None,
                    latency_ms=latency_ms,
                )
            )
            session.add_all(
                MessageSource(message_id=reply.id, chunk_id=c.chunk_id, rank=n, score=c.similarity)
                for n, c in enumerate(context, start=1)
            )
            await session.commit()

        cited = cited_numbers(answer_text, len(context))
        logger.info(
            "respuesta generada",
            extra={
                "conversation_id": conversation_id,
                "latency_ms": latency_ms,
                "retrieval_ms": retrieval_ms,
                "first_token_ms": first_token_ms,
                "tokens_in": stats.tokens_in if stats else None,
                "tokens_out": stats.tokens_out if stats else None,
                "tokens_per_second": stats.tokens_per_second if stats else None,
                "sources": len(context),
                "cited": cited,
            },
        )
        yield {
            "type": "end",
            "message_id": reply.id,
            "latency_ms": latency_ms,
            "tokens_in": reply.tokens_in,
            "tokens_out": reply.tokens_out,
            "tokens_per_second": stats.tokens_per_second if stats else None,
            "cited": cited,
        }

    async def _retrieve(self, text: str, user_id: int, budget: int) -> list[RetrievedChunk]:
        """Fragmentos relevantes; si la búsqueda falla, JARVIS responde sin ellos."""
        if self._retriever_factory is None:
            return []
        try:
            async with self._session_factory() as session:
                found = await self._retriever_factory(session).search(text, owner_user_id=user_id)
        except EmbeddingError as exc:
            logger.warning(
                "Búsqueda sin embeddings; se responde sin contexto", extra={"error": str(exc)}
            )
            return []
        return fit_context(found, budget)

    async def _get_or_create(
        self, repo: ConversationRepository, user_id: int, conversation_id: int | None, text: str
    ) -> Conversation:
        if conversation_id is not None:
            conversation = await repo.get_for_user(conversation_id, user_id)
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            return conversation
        return await repo.add(Conversation(user_id=user_id, title=make_title(text)))
