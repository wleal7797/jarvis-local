"""Voz a texto con faster-whisper (Whisper optimizado con CTranslate2), 100 % local.

Decisiones (ver docs/etapas/07-voz-a-texto.md):
- Modelo `small` en CPU, int8: 2,9 % de errores en español contra 18,7 % de `base`.
  En la GPU sería ~10 veces más rápido, pero la VRAM ya la ocupa el modelo de chat.
- `initial_prompt`: una frase con el vocabulario de la casa ("JARVIS") que guía a Whisper.
- VAD (Silero, incluido en faster-whisper): ignora los silencios antes y después de hablar.
- Se carga la primera vez que se usa y se descarga tras unos minutos sin uso (RAM).
"""

import asyncio
import io
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

MAX_AUDIO_SECONDS = 60


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Transcription:
    text: str
    language: str
    audio_seconds: float
    processing_seconds: float


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes) -> Transcription: ...


@dataclass(frozen=True)
class WhisperSettings:
    model: str = "small"
    language: str = "es"
    threads: int = 4
    compute_type: str = "int8"
    initial_prompt: str = "Conversación en español con JARVIS, el asistente de la casa."
    idle_unload_seconds: int = 300


def _default_factory(cfg: WhisperSettings) -> Any:
    from faster_whisper import WhisperModel  # importación tardía: tarda ~1 s

    return WhisperModel(
        cfg.model, device="cpu", compute_type=cfg.compute_type, cpu_threads=cfg.threads
    )


class FasterWhisperSTT:
    def __init__(
        self,
        settings: WhisperSettings | None = None,
        model_factory: Callable[[WhisperSettings], Any] | None = None,
    ) -> None:
        self._cfg = settings or WhisperSettings()
        self._factory = model_factory or _default_factory
        self._model: Any = None
        self._lock = threading.Lock()  # una transcripción a la vez: el CPU es uno solo
        self._last_used = 0.0

    @property
    def loaded(self) -> bool:
        return self._model is not None

    async def transcribe(self, audio: bytes) -> Transcription:
        if not audio:
            raise TranscriptionError("El audio está vacío")
        return await asyncio.to_thread(self._transcribe_sync, audio)

    def _transcribe_sync(self, audio: bytes) -> Transcription:
        with self._lock:
            started = time.perf_counter()
            if self._model is None:
                logger.info("cargando Whisper", extra={"model": self._cfg.model})
                self._model = self._factory(self._cfg)
            try:
                segments, info = self._model.transcribe(
                    io.BytesIO(audio),
                    language=self._cfg.language,
                    beam_size=1,
                    vad_filter=True,
                    condition_on_previous_text=False,
                    initial_prompt=self._cfg.initial_prompt,
                )
                if info.duration > MAX_AUDIO_SECONDS:
                    raise TranscriptionError(f"El audio supera {MAX_AUDIO_SECONDS} segundos")
                text = " ".join(segment.text.strip() for segment in segments).strip()
            except TranscriptionError:
                raise
            except Exception as exc:  # audio dañado o formato desconocido
                logger.warning("no se pudo transcribir", extra={"error": str(exc)})
                raise TranscriptionError("No se pudo leer el audio") from exc
            finally:
                self._last_used = time.monotonic()
            result = Transcription(
                text=text,
                language=info.language,
                audio_seconds=round(info.duration, 2),
                processing_seconds=round(time.perf_counter() - started, 2),
            )
            logger.info(
                "voz transcrita",
                extra={
                    "audio_s": result.audio_seconds,
                    "processing_s": result.processing_seconds,
                    "chars": len(text),
                },
            )
            return result

    def unload_if_idle(self) -> bool:
        """Libera la RAM del modelo si no se usa hace `idle_unload_seconds`."""
        with self._lock:
            idle = time.monotonic() - self._last_used
            if self._model is not None and idle >= self._cfg.idle_unload_seconds:
                self._model = None
                logger.info("Whisper descargado de la RAM por inactividad")
                return True
        return False

    async def run_idle_watcher(self, every_seconds: float = 60) -> None:
        """Tarea en segundo plano (la arranca `main.py`)."""
        while True:
            await asyncio.sleep(every_seconds)
            self.unload_if_idle()
