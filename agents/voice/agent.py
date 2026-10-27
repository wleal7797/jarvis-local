"""El agente de voz: micrófono siempre activo, "Jarvis" para llamarlo, conversación fluida.

Por cada frase que el segmentador entrega:

1. Se transcribe UNA sola vez con Whisper `small` en la API (en la GPU: ~0,5 s).
2. Si hace falta el nombre (dormido o mientras él habla): ¿empieza con "Jarvis"?
   - No → se ignora y se descarta. Nada se guarda.
   - Sí, pero es su propia voz (eco de los parlantes) → se ignora.
   - Sí y estaba hablando → se calla (interrupción).
3. Suena el aviso "le escucho" y la frase va al chat con voz; cada frase de la respuesta
   se reproduce en cuanto llega.
4. Al terminar de hablar, escucha unos segundos más sin pedir el nombre (modo conversación).

Cada paso se avisa a la pantalla (`notify`): escuchando → pensando → hablando → atento.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

from agents.voice.conversation import Conversation, Mode
from agents.voice.player import CHIME_ERROR
from agents.voice.segmenter import to_wav_bytes
from agents.voice.wake import NameDetector, mentions_name_at_start

logger = logging.getLogger("jarvis.voz")

Notify = Callable[[str, str], None]
SEARCHING_PHRASE = "Un momento, lo consulto."


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


def _no_notify(_state: str, _text: str) -> None:
    pass


class VoiceAgent:
    """`detector`: opcional, un detector por audio (openWakeWord, para el nombre en inglés).
    `name_from_text`: además (o en su lugar) busca "Jarvis" en la transcripción."""

    def __init__(
        self,
        detector: NameDetector | None,
        client: Client,
        player: PlayerLike,
        conversation: Conversation | None = None,
        verbose: bool = False,
        notify: Notify = _no_notify,
        name_from_text: bool = True,
        searching_wav: bytes | None = None,
    ) -> None:
        self.detector = detector
        self.client = client
        self.player = player
        self.conversation = conversation or Conversation()
        self.verbose = verbose
        self.notify = notify
        self.name_from_text = name_from_text or detector is None
        # Se dice mientras busca en los documentos (tarda ~10 s): así se sabe que está en ello.
        self.searching_wav = searching_wav
        self._busy = asyncio.Lock()
        # True sólo mientras llega la respuesta a una pregunta de verdad. (No basta con
        # `busy`: también es True mientras transcribe cualquier frase que oye en el cuarto.)
        self._answering = False
        self._stuck_since: float | None = None
        self.last_timings: dict[str, float] = {}

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    async def _transcribe(self, utterance: np.ndarray) -> str:
        return (await self.client.transcribe(to_wav_bytes(utterance))).strip()

    async def _called(self, utterance: np.ndarray) -> tuple[bool, str, str | None]:
        """¿Lo llamaron? Devuelve (llamado, lo que se oyó, transcripción si ya se hizo)."""
        if self.detector is not None:
            detection = await asyncio.to_thread(self.detector.detect, utterance)
            if detection.called or not self.name_from_text:
                return detection.called, detection.text, None
        try:
            text = await self._transcribe(utterance)
        except Exception as exc:
            logger.warning("no se pudo transcribir", extra={"error": str(exc)})
            return False, "", None
        return mentions_name_at_start(text), text, text

    async def handle(self, utterance: np.ndarray) -> str:
        """Procesa una frase. Devuelve qué pasó (útil para pruebas y registros)."""
        if self._busy.locked():
            return "ocupado"
        async with self._busy:
            started = time.perf_counter()
            timings: dict[str, float] = {}
            text: str | None = None
            if self.conversation.needs_name():
                called, heard, text = await self._called(utterance)
                timings["nombre"] = time.perf_counter() - started
                if not called:
                    if self.verbose:
                        status(f'   (oí: "{heard or "…"}" · no empieza con "Jarvis")')
                    return "ignorada"
                if self.player.playing:
                    if self.conversation.is_echo(heard):
                        return "eco"
                    self.player.stop()
                    self.conversation.interrupted()
                    status("Interrumpido: le escucho.")
            self._answering = True
            try:
                return await self._answer(utterance, text, started, timings)
            finally:
                self._answering = False
                if not self.player.playing:
                    self.on_player_idle_now()

    async def _answer(
        self, utterance: np.ndarray, text: str | None, started: float, timings: dict[str, float]
    ) -> str:
        """Le hablaron a él: transcribe (si hace falta), pregunta y habla."""
        self.conversation.attending()
        self.player.chime()

        if text is None:
            status("Le escucho…")
            self.notify("escuchando", "")
            try:
                text = await self._transcribe(utterance)
            except Exception as exc:
                logger.warning("no se pudo transcribir", extra={"error": str(exc)})
                return self._failed("error")
            timings["transcribir"] = time.perf_counter() - started
        if not text:
            return self._failed("vacía")

        status(f"Usted: {text}")
        status("Pensando…")
        self.notify("pensando", text)
        answer: list[str] = []
        try:
            async for event in self.client.chat(text, self.conversation.conversation_id):
                kind = event["type"]
                if kind == "start":
                    self.conversation.started_conversation(event["conversation_id"])
                elif kind == "searching":
                    self.notify("buscando", text)
                    if self.searching_wav:
                        self.conversation.speaking(SEARCHING_PHRASE)
                        self.player.enqueue(self.searching_wav, SEARCHING_PHRASE)
                elif kind == "token":
                    answer.append(event["content"])
                elif kind == "audio":
                    if "primera voz" not in timings:
                        timings["primera voz"] = time.perf_counter() - started
                        self.notify("hablando", text)
                    self.conversation.speaking(event.get("text", ""))
                    self.player.enqueue(event["wav"], event.get("text", ""))
                elif kind == "error":
                    self.player.chime(CHIME_ERROR)
        except Exception as exc:
            logger.warning("falló el chat", extra={"error": str(exc)})
            return self._failed("error")
        status(f"JARVIS: {''.join(answer).strip()}")
        status(
            "   tiempos desde que dejó de hablar: "
            + " · ".join(f"{name} {seconds:.1f} s" for name, seconds in timings.items())
        )
        self.last_timings = timings
        return "respondida"

    def _failed(self, result: str) -> str:
        self.player.chime(CHIME_ERROR)
        return result

    def on_player_idle_now(self) -> None:
        """Terminó (o no hubo nada que decir): vuelve a esperar."""
        self.conversation.finished_speaking()
        waiting = self.conversation.settings.follow_up_seconds <= 0
        self.notify("en_espera" if waiting else "atento", "")

    def on_player_idle(self) -> None:
        """La llama el reproductor cuando termina de hablar."""
        if self._answering:
            # Terminó una frase (o "Un momento, lo consulto") pero la respuesta sigue
            # llegando: al terminarla, `handle` revisa si ya se calló.
            return
        self.on_player_idle_now()
        seconds = self.conversation.settings.follow_up_seconds
        if seconds > 0:
            status(f"Le sigo escuchando {seconds:.0f} s…")

    async def say_notice(self, notice: dict) -> None:
        """Dice en voz alta un aviso (recordatorio). Si está respondiendo algo, va después."""
        text = notice.get("say") or notice.get("text") or ""
        if not text:
            return
        status(f"Aviso: {text}")
        try:
            wav = await self.client.speak(text)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("no se pudo decir el aviso", extra={"error": str(exc)})
            self.player.chime()
            return
        self.player.chime()
        self.conversation.speaking(text)  # su propia voz no lo despierta (eco)
        self.player.enqueue(wav, text)
        self.notify("hablando", text)

    def check_stuck(self, now: float | None = None, after_seconds: float = 3.0) -> bool:
        """Vigilante: si dice "hablando" o "atendiendo" pero ya no suena nada ni está
        respondiendo hace más de 3 s, vuelve a "en espera". El bucle del micrófono lo llama
        todo el tiempo. Devuelve True si tuvo que corregir el estado."""
        now = time.monotonic() if now is None else now
        stuck = (
            self.conversation.mode in (Mode.HABLANDO, Mode.ATENDIENDO)
            and not self._answering
            and not self.player.playing
        )
        if not stuck:
            self._stuck_since = None
            return False
        if self._stuck_since is None:
            self._stuck_since = now
            return False
        if now - self._stuck_since < after_seconds:
            return False
        self._stuck_since = None
        logger.warning("estado trabado corregido", extra={"modo": self.conversation.mode.value})
        self.on_player_idle_now()
        return True
