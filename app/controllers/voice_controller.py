"""Controlador de voz: convierte un audio grabado en texto.

El navegador graba mientras hablas (botón de micrófono), envía el audio una sola vez y
recibe el texto, que luego se manda al chat como cualquier mensaje.

Por qué una petición HTTP y no un WebSocket (como decía el plan): con "pulsar para hablar"
el audio se envía completo una sola vez, y HTTP es más simple de probar y de depurar.
El WebSocket de audio continuo llega con la palabra de activación (Etapa 9).
"""

import asyncio
import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.core.dependencies import (
    CurrentUserDep,
    LLMDep,
    MemberDep,
    OwnerDep,
    SpeechToTextDep,
    TextToSpeechDep,
    VoiceStatusDep,
)
from app.core.preferences import save_preferences
from app.schemas.voice import (
    AgentStatusIn,
    AgentStatusOut,
    SpeakIn,
    TranscriptionOut,
    VoiceSettingsIn,
    VoiceSettingsOut,
    WarmOut,
)
from app.services.llm import LLMError
from app.services.stt_service import TranscriptionError
from app.services.tts_service import SpeechError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voz"])
ws_router = APIRouter(tags=["voz"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB: más que suficiente para 60 s de voz


@router.post(
    "/transcribe",
    response_model=TranscriptionOut,
    summary="Voz a texto (WebM/Opus del navegador, WAV, MP3, OGG…)",
)
async def transcribe(
    user: CurrentUserDep,
    stt: SpeechToTextDep,
    audio: Annotated[UploadFile, File(description="Audio grabado")],
):
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "El audio supera 10 MB")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El audio está vacío")
    try:
        result = await stt.transcribe(data)
    except TranscriptionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return TranscriptionOut(**vars(result))


@router.post(
    "/speak",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}},
    summary="Texto a voz: devuelve un WAV con la voz de JARVIS",
)
async def speak(body: SpeakIn, user: CurrentUserDep, tts: TextToSpeechDep) -> Response:
    try:
        audio = await tts.synthesize(body.text)
    except SpeechError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return Response(
        content=audio.wav,
        media_type="audio/wav",
        headers={"X-Audio-Seconds": str(audio.audio_seconds)},
    )


def _settings_out(tts) -> VoiceSettingsOut:
    return VoiceSettingsOut(
        voice=tts.voice_name,
        length_scale=tts.length_scale,
        effect=tts.effect,
        installed=tts.installed_voices(),
    )


@router.get("/settings", response_model=VoiceSettingsOut, summary="Voz actual y voces instaladas")
async def get_voice_settings(user: CurrentUserDep, tts: TextToSpeechDep):
    return _settings_out(tts)


@router.put(
    "/settings",
    response_model=VoiceSettingsOut,
    summary="Cambiar la voz o la velocidad (se aplica al instante y se recuerda)",
)
async def update_voice_settings(body: VoiceSettingsIn, user: MemberDep, tts: TextToSpeechDep):
    try:
        tts.configure(voice=body.voice, length_scale=body.length_scale, effect=body.effect)
    except SpeechError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    save_preferences(
        {
            "tts_voice": tts.voice_name,
            "tts_length_scale": tts.length_scale,
            "tts_effect": tts.effect,
        }
    )
    return _settings_out(tts)


@router.post(
    "/warm",
    response_model=WarmOut,
    summary="Dejar listos Whisper, la voz y el modelo de chat (los llama el agente de voz)",
)
async def warm(
    user: OwnerDep,
    stt: SpeechToTextDep,
    tts: TextToSpeechDep,
    llm: LLMDep,
    prefill: bool = False,
):
    """Sin esto, tras unos minutos de silencio la primera respuesta esperaba ~10 s a que
    se cargaran los modelos. El agente lo llama al arrancar (con `prefill`) y cada 4 minutos."""
    result = {"stt": False, "tts": False, "llm": False}
    for name, model in (("stt", stt), ("tts", tts)):
        try:
            await asyncio.to_thread(model.warm)
            result[name] = True
        except Exception as exc:  # una pieza que falla no impide calentar las demás
            logger.warning("no se pudo precargar", extra={"model": name, "error": str(exc)})
    try:
        await llm.warm("10m", prefill=prefill)
        result["llm"] = True
    except LLMError as exc:
        logger.warning("no se pudo precargar el modelo de chat", extra={"error": str(exc)})
    return WarmOut(**result)


@router.get("/agent", response_model=AgentStatusOut, summary="Qué está haciendo el agente de voz")
async def get_agent_status(user: CurrentUserDep, hub: VoiceStatusDep):
    return AgentStatusOut(**hub.current.as_dict())


@router.put("/agent", response_model=AgentStatusOut, summary="El agente de voz avisa su estado")
async def put_agent_status(body: AgentStatusIn, user: OwnerDep, hub: VoiceStatusDep):
    try:
        current = hub.publish(body.state, body.text)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return AgentStatusOut(**current.as_dict())


@ws_router.websocket("/ws/voice-status")
async def voice_status_socket(
    websocket: WebSocket, user: CurrentUserDep, hub: VoiceStatusDep
) -> None:
    """Empuja al navegador cada cambio de estado del agente de voz."""
    await websocket.accept()
    queue = hub.subscribe()
    try:
        while True:
            update = await queue.get()
            await websocket.send_json(update.as_dict())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(queue)
