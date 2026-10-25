"""Controlador de voz: convierte un audio grabado en texto.

El navegador graba mientras hablas (botón de micrófono), envía el audio una sola vez y
recibe el texto, que luego se manda al chat como cualquier mensaje.

Por qué una petición HTTP y no un WebSocket (como decía el plan): con "pulsar para hablar"
el audio se envía completo una sola vez, y HTTP es más simple de probar y de depurar.
El WebSocket de audio continuo llega con la palabra de activación (Etapa 9).
"""

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status

from app.core.dependencies import CurrentUserDep, SpeechToTextDep, TextToSpeechDep
from app.schemas.voice import SpeakIn, TranscriptionOut
from app.services.stt_service import TranscriptionError
from app.services.tts_service import SpeechError

router = APIRouter(prefix="/api/voice", tags=["voz"])

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
