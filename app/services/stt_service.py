"""Voz a texto con faster-whisper (Whisper optimizado con CTranslate2), 100 % local.

Decisiones (ver docs/etapas/07-voz-a-texto.md):
- Modelo `small`: 2,9 % de errores en español contra 18,7 % de `base`.
- En la GPU (Etapa 9): 0,5 s por frase en vez de ~3 s en la CPU. Ocupa ~350 MB de VRAM y
  el modelo de chat sigue cabiendo entero. Usa la librería CUDA que ya trae Ollama
  (`cublas64_12.dll`), así que no hay que instalar nada. Si la GPU falla, vuelve a la CPU.
- `initial_prompt`: una frase con el vocabulario de la casa ("JARVIS") que guía a Whisper.
- VAD (Silero, incluido en faster-whisper): ignora los silencios antes y después de hablar.
- Se carga la primera vez que se usa y se descarga tras unos minutos sin uso (RAM).
"""

import asyncio
import io
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

MAX_AUDIO_SECONDS = 60

# El nombre se pronuncia "Yarbis": si Whisper lo escribe como suena, se corrige a "Jarvis".
_NAME_VARIANTS = re.compile(
    r"\b(?:[yjhl]{1,2}ar[bv]i[sz]|[yjh]ar[bv]ys|yarbi|jarbis|harbys|llarvis)\b", re.IGNORECASE
)


def normalize_name(text: str) -> str:
    return _NAME_VARIANTS.sub("Jarvis", text)


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
    def warm(self) -> None: ...


@dataclass(frozen=True)
class WhisperSettings:
    model: str = "small"
    # "auto": GPU si se puede, si no CPU. También "cuda" o "cpu".
    device: str = "auto"
    language: str = "es"
    threads: int = 4
    compute_type: str = "int8"
    initial_prompt: str = (
        "Conversación en español con Jarvis (se pronuncia Yarbis), el asistente de la casa."
    )
    idle_unload_seconds: int = 300


def _ollama_cuda_dir() -> str | None:
    """Carpeta con las librerías CUDA 12 que instala Ollama (cuBLAS), si existe."""
    base = os.environ.get("LOCALAPPDATA", "")
    candidate = os.path.join(base, "Programs", "Ollama", "lib", "ollama", "cuda_v12")
    return candidate if os.path.isfile(os.path.join(candidate, "cublas64_12.dll")) else None


def _load_whisper(cfg: WhisperSettings, device: str) -> Any:
    from faster_whisper import WhisperModel  # importación tardía: tarda ~1 s

    compute_type = "int8_float16" if device == "cuda" else cfg.compute_type
    kwargs = {"device": device, "compute_type": compute_type, "cpu_threads": cfg.threads}
    try:  # sin internet: usa el modelo ya descargado
        return WhisperModel(cfg.model, local_files_only=True, **kwargs)
    except Exception:  # la primera vez hay que descargarlo
        return WhisperModel(cfg.model, **kwargs)


def _default_factory(cfg: WhisperSettings) -> Any:
    if cfg.device in ("auto", "cuda"):
        cuda_dir = _ollama_cuda_dir()
        if cuda_dir and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(cuda_dir)
            os.environ["PATH"] = cuda_dir + os.pathsep + os.environ.get("PATH", "")
        try:
            model = _load_whisper(cfg, "cuda")
            # La librería CUDA se carga al transcribir: se prueba con medio segundo de silencio.
            segments, _ = model.transcribe(_silence(0.5), language=cfg.language)
            list(segments)
            logger.info("Whisper en la GPU", extra={"model": cfg.model})
            return model
        except Exception as exc:
            if cfg.device == "cuda":
                raise
            logger.warning("Whisper no pudo usar la GPU; usa la CPU", extra={"error": str(exc)})
    return _load_whisper(cfg, "cpu")


def _silence(seconds: float) -> Any:
    import numpy as np

    return np.zeros(int(16000 * seconds), dtype=np.float32)


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
                text = normalize_name(" ".join(s.text.strip() for s in segments).strip())
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

    def warm(self) -> None:
        """Carga el modelo si hace falta y reinicia la cuenta de inactividad."""
        with self._lock:
            if self._model is None:
                logger.info("cargando Whisper", extra={"model": self._cfg.model})
                self._model = self._factory(self._cfg)
            self._last_used = time.monotonic()

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
