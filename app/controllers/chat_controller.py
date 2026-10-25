"""Controlador del chat: conversar con JARVIS y consultar el historial."""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import ChatServiceDep, CurrentUserDep, SessionDep
from app.repositories import ConversationRepository
from app.schemas.chat import ChatIn, ConversationOut, MessageOut
from app.services.chat_service import ChatEvent, ConversationNotFoundError

router = APIRouter(prefix="/api", tags=["chat"])

NOT_FOUND = "Conversación no encontrada"


async def _ndjson(events: AsyncIterator[ChatEvent]) -> AsyncIterator[str]:
    async for event in events:
        yield json.dumps(event, ensure_ascii=False) + "\n"


@router.post(
    "/chat",
    summary="Enviar un mensaje a JARVIS (respuesta en streaming)",
    response_description=(
        "NDJSON: una línea por evento. `start` (ids), varios `token` (texto), "
        "`end` (estadísticas) o `error`."
    ),
)
async def chat(body: ChatIn, user: CurrentUserDep, service: ChatServiceDep) -> StreamingResponse:
    # Se valida antes de empezar a transmitir: después ya no se puede devolver un 404.
    if body.conversation_id is not None:
        try:
            await service.ensure_conversation(user.id, body.conversation_id)
        except ConversationNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND) from None

    events = service.answer(user.id, body.message, body.conversation_id)
    return StreamingResponse(_ndjson(events), media_type="application/x-ndjson")


@router.get("/conversations", response_model=list[ConversationOut], summary="Mis conversaciones")
async def list_conversations(user: CurrentUserDep, session: SessionDep):
    return await ConversationRepository(session).list_for_user(user.id)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
    summary="Mensajes de una conversación",
)
async def list_messages(conversation_id: int, user: CurrentUserDep, session: SessionDep):
    repo = ConversationRepository(session)
    if await repo.get_for_user(conversation_id, user.id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return await repo.messages(conversation_id)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una conversación y todos sus mensajes",
)
async def delete_conversation(conversation_id: int, user: CurrentUserDep, session: SessionDep):
    repo = ConversationRepository(session)
    conversation = await repo.get_for_user(conversation_id, user.id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    await repo.delete(conversation)
