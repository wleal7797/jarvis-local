"""El agente de voz: micrófono siempre activo, "Jarvis" para llamarlo, conversación fluida.

Por cada frase que el segmentador entrega:

1. Si hace falta el nombre (dormido o mientras él habla): ¿empieza con "Jarvis"?
   - No → se ignora. Nada sale del PC: la frase se descarta.
   - Sí, pero es su propia voz (eco de los parlantes) → se ignora.
   - Sí y estaba hablando → se calla (interrupción).
2. Suena el aviso "te escucho".
3. La frase completa se transcribe con Whisper `small` (preciso) en la API.
4. Se envía al chat con voz; cada frase de la respuesta se reproduce en cuanto llega.
5. Al terminar de hablar, escucha unos segundos más sin pedir el nombre (modo conversación).
"""

import asyncio
import logging
import time
from typing import Any, Protocol

import numpy as np

from agents.voice.conversation import Conversation
from agents.voice.player import CHIME_ERROR
from agents.voice.segmenter import to_wav_bytes
from agents.voice.wake import NameDetector

logger = logging.getLogger("jarvis.voz")


class Client(Protocol):
    async def transcribe(self, wav: bytes) -> str: ...
    def chat(self, text: str, conversation_id: int | None) -> Any: ...


class PlayerLike(Protocol):
    playing: bool

    def enqueue(self, wav: bytes, sentence: str = "") -> None: ...
    def chime(self, audio: np.ndarray = ..., rate: int = ...) -> None: ...
    def stop(self) -> None: ...


def status(text: str) -> None:
    """Mensajes cortos para quien mira la terminal."""
    print(text, flush=True)


class VoiceAgent:
    def __init__(
        self,
        detector: NameDetector,
        client: Client,
        player: PlayerLike,
        conversation: Conversation | None = None,
    ) -> None:
        self.detector = detector
        self.client = client
        self.player = player
        self.conversation = conversation or Conversation()
        self._busy = asyncio.Lock()
        self.last_timings: dict[str, float] = {}

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    async def handle(self, utterance: np.ndarray) -> str:
        """Procesa una frase. Devuelve qué pasó (útil para pruebas y registros)."""
        if self._busy.locked():
            return "ocupado"
        async with self._busy:
            started = time.perf_counter()
            timings: dict[str, float] = {}
            if self.conversation.needs_name():
                detection = await asyncio.to_thread(self.detector.detect, utterance)
                timings["nombre"] = time.perf_counter() - started
                if not detection.called:
                    return "ignorada"
                if self.player.playing:
                    if self.conversation.is_echo(detection.text):
                        return "eco"
                    self.player.stop()
                    self.conversation.interrupted()
                    status("Interrumpido: le escucho.")
            self.conversation.attending()
            self.player.chime()
            status("Le escucho…")

            try:
                text = (await self.client.transcribe(to_wav_bytes(utterance))).strip()
                timings["transcribir"] = time.perf_counter() - started
            except Exception as exc:
                logger.warning("no se pudo transcribir", extra={"error": str(exc)})
                self.player.chime(CHIME_ERROR)
                self.conversation.finished_speaking()
                return "error"
            if not text:
                self.player.chime(CHIME_ERROR)
                self.conversation.finished_speaking()
                return "vacía"

            status(f"Usted: {text}")
            answer: list[str] = []
            try:
                async for event in self.client.chat(text, self.conversation.conversation_id):
                    kind = event["type"]
                    if kind == "start":
                        self.conversation.started_conversation(event["conversation_id"])
                    elif kind == "token":
                        answer.append(event["content"])
                    elif kind == "audio":
                        timings.setdefault("primera voz", time.perf_counter() - started)
                        self.conversation.speaking(event.get("text", ""))
                        self.player.enqueue(event["wav"], event.get("text", ""))
                    elif kind == "error":
                        self.player.chime(CHIME_ERROR)
            except Exception as exc:
                logger.warning("falló el chat", extra={"error": str(exc)})
                self.player.chime(CHIME_ERROR)
                self.conversation.finished_speaking()
                return "error"
            status(f"JARVIS: {''.join(answer).strip()}")
            status(
                "   tiempos desde que dejó de hablar: "
                + " · ".join(f"{name} {seconds:.1f} s" for name, seconds in timings.items())
            )
            self.last_timings = timings
            if not self.player.playing:
                self.conversation.finished_speaking()
            return "respondida"

    def on_player_idle(self) -> None:
        """La llama el reproductor (desde su hilo) cuando termina de hablar."""
        self.conversation.finished_speaking()
        status(f"Le sigo escuchando {self.conversation.settings.follow_up_seconds:.0f} s…")
