"""Texto a voz con Piper, 100 % local.

Voz elegida escuchando muestras: `es_ES-davefx-medium` (hombre, España).
Genera ~12 s de audio por cada segundo de proceso en la CPU (ver docs/etapas/08-texto-a-voz.md).

Tres piezas:
- `clean_for_speech`: quita lo que no se debe leer en voz alta (Markdown, citas [1], enlaces).
- `SentenceSplitter`: corta la respuesta en frases *mientras el modelo escribe*, para que
  JARVIS empiece a hablar sin esperar a que termine.
- `PiperTTS`: convierte cada frase en audio WAV.
"""

import asyncio
import io
import logging
import re
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class SpeechError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpeechAudio:
    wav: bytes
    audio_seconds: float
    processing_seconds: float


class TextToSpeech(Protocol):
    async def synthesize(self, text: str) -> SpeechAudio: ...


# ---------- Limpiar el texto antes de leerlo ----------

_CITATION = re.compile(r"\s*\[\d{1,2}(?:\s*,\s*\d{1,2})*\]")
_URL = re.compile(r"https?://\S+")
_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN = re.compile(r"(\*\*|__|\*|_|`|~~)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.MULTILINE)
_EMOJI = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f2ff]")
_SPACES = re.compile(r"[ \t]+")
# El nombre se dice en inglés: "Yárbis" (la tilde marca el acento, como en inglés: YAR-bis).
_NAME = re.compile(r"\b(?:J\.A\.R\.V\.I\.S\.|jarvis\b)", re.IGNORECASE)
NAME_PRONUNCIATION = "Yárbis"


def clean_for_speech(text: str) -> str:
    text = _CODE_BLOCK.sub(" (hay un bloque de código en pantalla) ", text)
    text = _CITATION.sub("", text)
    text = _URL.sub("el enlace en pantalla", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("", text)
    text = _MARKDOWN.sub("", text)
    text = _EMOJI.sub("", text)
    text = _NAME.sub(NAME_PRONUNCIATION, text)
    return _SPACES.sub(" ", text).strip()


# ---------- Cortar en frases mientras llega el texto ----------

# Fin de frase: . ! ? … seguido de espacio o salto de línea. No corta "3.5" ni "Sr.".
_SENTENCE_END = re.compile(r"(?<!\b[A-ZÁÉÍÓÚa-záéíóú]{1}\.)(?<=[.!?…])[\"”»)]*\s+|\n{2,}")
MIN_SENTENCE_CHARS = 25  # las frases muy cortas se juntan con la siguiente (suena más natural)


class SentenceSplitter:
    """Recibe pedazos de texto y entrega frases completas, listas para hablar."""

    def __init__(self, min_chars: int = MIN_SENTENCE_CHARS) -> None:
        self._buffer = ""
        self._min_chars = min_chars

    def feed(self, piece: str) -> list[str]:
        self._buffer += piece
        sentences: list[str] = []
        start = 0
        for match in _SENTENCE_END.finditer(self._buffer):
            candidate = self._buffer[start : match.end()].strip()
            if len(candidate) >= self._min_chars:
                sentences.append(candidate)
                start = match.end()
        self._buffer = self._buffer[start:]
        return sentences

    def flush(self) -> list[str]:
        rest = self._buffer.strip()
        self._buffer = ""
        return [rest] if rest else []


# ---------- Piper ----------


@dataclass(frozen=True)
class PiperSettings:
    voices_dir: str = "data/tts/piper"
    voice: str = "es_ES-davefx-medium"
    # >1 habla más despacio, <1 más rápido.
    length_scale: float = 1.0
    idle_unload_seconds: int = 600


def _default_loader(cfg: PiperSettings) -> Any:
    from piper import PiperVoice  # importación tardía

    path = Path(cfg.voices_dir) / f"{cfg.voice}.onnx"
    if not path.exists():
        raise SpeechError(
            f"No se encontró la voz {cfg.voice}. Ejecuta: python -m scripts.download_tts_voices"
        )
    return PiperVoice.load(str(path))


class PiperTTS:
    def __init__(
        self,
        settings: PiperSettings | None = None,
        voice_loader: Callable[[PiperSettings], Any] | None = None,
    ) -> None:
        self._cfg = settings or PiperSettings()
        self._loader = voice_loader or _default_loader
        self._voice: Any = None
        self._lock = threading.Lock()
        self._last_used = 0.0

    @property
    def voice_name(self) -> str:
        return self._cfg.voice

    @property
    def length_scale(self) -> float:
        return self._cfg.length_scale

    @property
    def loaded(self) -> bool:
        return self._voice is not None

    def installed_voices(self) -> list[dict[str, str]]:
        """Voces de Piper descargadas en `voices_dir` (cada una es un .onnx + su .json)."""
        voices = []
        for model in sorted(Path(self._cfg.voices_dir).glob("*.onnx")):
            name = model.stem  # es_ES-davefx-medium
            parts = name.split("-")
            voices.append(
                {
                    "name": name,
                    "language": parts[0] if parts else "",
                    "speaker": parts[1] if len(parts) > 1 else name,
                    "quality": parts[2] if len(parts) > 2 else "",
                }
            )
        return voices

    def configure(self, voice: str | None = None, length_scale: float | None = None) -> None:
        """Cambia la voz o la velocidad en caliente (la próxima frase ya usa la nueva)."""
        if voice is not None and voice not in {v["name"] for v in self.installed_voices()}:
            raise SpeechError(f"La voz {voice} no está descargada")
        if length_scale is not None and not 0.5 <= length_scale <= 2.0:
            raise SpeechError("La velocidad debe estar entre 0.5 y 2.0")
        with self._lock:
            new_voice = voice or self._cfg.voice
            if new_voice != self._cfg.voice:
                self._voice = None  # se carga la nueva en la próxima frase
            self._cfg = PiperSettings(
                voices_dir=self._cfg.voices_dir,
                voice=new_voice,
                length_scale=length_scale if length_scale is not None else self._cfg.length_scale,
                idle_unload_seconds=self._cfg.idle_unload_seconds,
            )
        logger.info(
            "voz configurada", extra={"voice": new_voice, "length_scale": self._cfg.length_scale}
        )

    async def synthesize(self, text: str) -> SpeechAudio:
        spoken = clean_for_speech(text)
        if not spoken:
            raise SpeechError("No hay texto para leer")
        return await asyncio.to_thread(self._synthesize_sync, spoken)

    def _synthesize_sync(self, text: str) -> SpeechAudio:
        with self._lock:
            started = time.perf_counter()
            if self._voice is None:
                logger.info("cargando voz", extra={"voice": self._cfg.voice})
                self._voice = self._loader(self._cfg)
            buffer = io.BytesIO()
            try:
                from piper import SynthesisConfig

                config = SynthesisConfig(length_scale=self._cfg.length_scale)
                with wave.open(buffer, "wb") as wav_file:
                    self._voice.synthesize_wav(text, wav_file, syn_config=config)
            except Exception as exc:
                raise SpeechError(f"No se pudo generar la voz: {exc}") from exc
            finally:
                self._last_used = time.monotonic()
            data = buffer.getvalue()
            with wave.open(io.BytesIO(data)) as wav_file:
                seconds = wav_file.getnframes() / wav_file.getframerate()
            return SpeechAudio(
                wav=data,
                audio_seconds=round(seconds, 2),
                processing_seconds=round(time.perf_counter() - started, 3),
            )

    def unload_if_idle(self) -> bool:
        with self._lock:
            if self._voice is not None and (
                time.monotonic() - self._last_used >= self._cfg.idle_unload_seconds
            ):
                self._voice = None
                logger.info("voz descargada de la RAM por inactividad")
                return True
        return False

    async def run_idle_watcher(self, every_seconds: float = 60) -> None:
        while True:
            await asyncio.sleep(every_seconds)
            self.unload_if_idle()
