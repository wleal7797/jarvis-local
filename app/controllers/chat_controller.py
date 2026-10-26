"""Controlador del chat: conversar con JARVIS y consultar el historial."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.core.dependencies import ChatServiceDep, CurrentUserDep, SessionDep, TextToSpeechDep
from app.repositories import ConversationRepository
from app.schemas.chat import ChatIn, ConversationOut, MessageOut
from app.services.chat_service import ChatEvent, ConversationNotFoundError
from app.services.speech_pipeline import stream_with_voice

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])
ws_router = APIRouter(tags=["chat"])

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
    messages = await repo.messages(conversation_id)
    sources = await repo.sources_for([m.id for m in messages])
    return [
        MessageOut.model_validate(m).model_copy(update={"sources": sources.get(m.id, [])})
        for m in messages
    ]


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


@ws_router.websocket("/ws/chat")
async def chat_ws(
    websocket: WebSocket, user: CurrentUserDep, service: ChatServiceDep, tts: TextToSpeechDep
) -> None:
    """Chat en vivo para la vista web.

    El navegador envía `{"message": "...", "conversation_id": 1 | null, "voice": true}` y recibe
    los mismos eventos que `POST /api/chat` (`start`, `sources`, `token`, `end`, `error`).
    Con `"voice": true` llegan además `audio` (una frase hablada, WAV en base64) y `audio_end`.
    La conexión queda abierta para seguir conversando.
    """
    await websocket.accept()
    send_lock = asyncio.Lock()  # el texto y el audio se envían desde dos tareas

    async def send(event: ChatEvent) -> None:
        async with send_lock:
            await websocket.send_json(event)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                body = ChatIn.model_validate_json(raw)
            except ValidationError:
                await websocket.send_json({"type": "error", "message": "Mensaje inválido."})
                continue
            if body.conversation_id is not None:
                try:
                    await service.ensure_conversation(user.id, body.conversation_id)
                except ConversationNotFoundError:
                    await websocket.send_json({"type": "error", "message": NOT_FOUND})
                    continue
            events = service.answer(user.id, body.message, body.conversation_id, voice=body.voice)
            if body.voice:
                await stream_with_voice(events, tts, send)
            else:
                async for event in events:
                    await send(event)
    except WebSocketDisconnect:
        logger.info("WebSocket cerrado por el navegador")
