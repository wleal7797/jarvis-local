"""Une el chat en streaming con la voz: JARVIS habla mientras sigue escribiendo.

    texto del modelo ──► SentenceSplitter ──► cola ──► Piper ──► {"type": "audio"} ──► navegador
                    └──────────────────────► {"type": "token"} (el texto sigue llegando)

La síntesis corre en una tarea aparte, así el texto no espera al audio.
"""

import asyncio
import base64
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.services.tts_service import SentenceSplitter, SpeechError, TextToSpeech

logger = logging.getLogger(__name__)

Event = dict[str, Any]
Send = Callable[[Event], Awaitable[None]]


async def _speaker(queue: asyncio.Queue[str | None], tts: TextToSpeech, send: Send) -> None:
    seq = 0
    failed = False
    while (sentence := await queue.get()) is not None:
        if failed:
            continue
        try:
            audio = await tts.synthesize(sentence)
        except SpeechError as exc:
            if "No hay texto" in str(exc):
                continue
            failed = True
            logger.warning("no se pudo hablar", extra={"error": str(exc)})
            await send({"type": "audio_error", "message": str(exc)})
            continue
        await send(
            {
                "type": "audio",
                "seq": seq,
                "text": sentence,
                "audio": base64.b64encode(audio.wav).decode("ascii"),
                "audio_seconds": audio.audio_seconds,
                "processing_seconds": audio.processing_seconds,
            }
        )
        seq += 1
    await send({"type": "audio_end", "sentences": seq})


async def stream_with_voice(events: AsyncIterator[Event], tts: TextToSpeech, send: Send) -> None:
    """Reenvía los eventos del chat y, en paralelo, los de audio de cada frase."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    speaker = asyncio.create_task(_speaker(queue, tts, send))
    splitter = SentenceSplitter()
    try:
        async for event in events:
            await send(event)
            if event["type"] == "token":
                for sentence in splitter.feed(event["content"]):
                    queue.put_nowait(sentence)
            elif event["type"] in ("end", "error"):
                if event["type"] == "end":
                    for sentence in splitter.flush():
                        queue.put_nowait(sentence)
                break
    finally:
        queue.put_nowait(None)
        await speaker
