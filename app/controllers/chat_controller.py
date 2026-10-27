"""Controlador del chat: conversar con JARVIS (sólo la sesión de ahora, sin historial)."""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.core.dependencies import (
    ChatServiceDep,
    CurrentUserDep,
    MemoryServiceDep,
    TextToSpeechDep,
)
from app.schemas.chat import ChatIn
from app.services.chat_service import ChatEvent, ConversationNotFoundError
from app.services.memory_service import Learned, MemoryService
from app.services.speech_pipeline import stream_with_voice

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])
ws_router = APIRouter(tags=["chat"])

NOT_FOUND = "Conversación no encontrada"


# Tareas de "¿hay algo que recordar?" que siguen corriendo después de responder.
_learning: set[asyncio.Task] = set()


def memory_event(learned: Learned) -> ChatEvent:
    return {
        "type": "memory",
        "memory_id": learned.memory_id,
        "content": learned.content,
        "updated": learned.updated,
    }


async def _tap_end(events: AsyncIterator[ChatEvent], seen: dict) -> AsyncIterator[ChatEvent]:
    """Deja pasar los eventos y anota el id de la respuesta cuando termina."""
    async for event in events:
        # Si usó herramientas (un recordatorio, por ejemplo) no hay nada que aprender:
        # quedaría un recuerdo viejo ("debe sacar la basura el 27 de octubre").
        if event["type"] == "end" and not event.get("tools"):
            seen["message_id"] = event["message_id"]
        yield event


def learn_later(
    memory: MemoryService,
    user_id: int,
    message_id: int,
    send: Callable[[ChatEvent], Awaitable[None]],
) -> None:
    """Revisa en segundo plano si hay algo que recordar (no demora la respuesta)."""

    async def run() -> None:
        for learned in await memory.learn(user_id, message_id):
            with contextlib.suppress(Exception):  # el navegador pudo haberse ido
                await send(memory_event(learned))

    task = asyncio.create_task(run())
    _learning.add(task)
    task.add_done_callback(_learning.discard)


async def _ndjson(
    events: AsyncIterator[ChatEvent], memory: MemoryService | None, user_id: int, user_role: str
) -> AsyncIterator[str]:
    seen: dict = {}
    async for event in _tap_end(events, seen):
        yield json.dumps(event, ensure_ascii=False) + "\n"
    if memory is not None and "message_id" in seen and user_role != "guest":
        for learned in await memory.learn(user_id, seen["message_id"]):
            yield json.dumps(memory_event(learned), ensure_ascii=False) + "\n"


@router.post(
    "/chat",
    summary="Enviar un mensaje a JARVIS (respuesta en streaming)",
    response_description=(
        "NDJSON: una línea por evento. `start` (ids), varios `token` (texto), "
        "`end` (estadísticas) o `error`. Si aprendió algo de usted, al final llega `memory`."
    ),
)
async def chat(
    body: ChatIn, user: CurrentUserDep, service: ChatServiceDep, memory: MemoryServiceDep
) -> StreamingResponse:
    # Se valida antes de empezar a transmitir: después ya no se puede devolver un 404.
    if body.conversation_id is not None:
        try:
            await service.ensure_conversation(user.id, body.conversation_id)
        except ConversationNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND) from None

    events = service.answer(user.id, body.message, body.conversation_id, role=user.role)
    return StreamingResponse(
        _ndjson(events, memory, user.id, user.role), media_type="application/x-ndjson"
    )


# Sin endpoints para ver conversaciones viejas (a pedido del dueño): el chat sólo muestra
# la sesión de ahora. Las conversaciones quedan guardadas para que JARVIS aprenda
# (memoria, calificaciones), pero ninguna pantalla ni petición las devuelve.


@ws_router.websocket("/ws/chat")
async def chat_ws(
    websocket: WebSocket,
    user: CurrentUserDep,
    service: ChatServiceDep,
    tts: TextToSpeechDep,
    memory: MemoryServiceDep,
) -> None:
    """Chat en vivo para la vista web.

    El navegador envía `{"message": "...", "conversation_id": 1 | null, "voice": true}` y recibe
    los mismos eventos que `POST /api/chat` (`start`, `sources`, `token`, `end`, `error`).
    Con `"voice": true` llegan además `audio` (una frase hablada, WAV en base64) y `audio_end`.
    Si después de responder aprende algo de usted, llega `memory` (Etapa 10).
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
            seen: dict = {}
            events = _tap_end(
                service.answer(
                    user.id,
                    body.message,
                    body.conversation_id,
                    voice=body.voice,
                    role=user.role,
                ),
                seen,
            )
            if body.voice:
                await stream_with_voice(events, tts, send)
            else:
                async for event in events:
                    await send(event)
            # De los invitados no se aprende nada (son visitas, no la familia).
            if "message_id" in seen and user.role != "guest":
                learn_later(memory, user.id, seen["message_id"], send)
    except WebSocketDisconnect:
        logger.info("WebSocket cerrado por el navegador")
