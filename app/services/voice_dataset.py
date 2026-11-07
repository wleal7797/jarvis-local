"""Grabaciones para entrenar una voz propia de Piper (mejora adicional a la V1).

El dueño lee frases en voz alta desde la página **Grabar mi voz**; cada grabación se
guarda lista para entrenar, en el formato que pide Piper (estilo LJSpeech):

    data/voz-propia/
    ├── wavs/frase_0001.wav      WAV mono 22 050 Hz, 16 bits, sin silencios al borde
    └── metadata.csv             frase_0001.wav|Buenas noches, todo está en orden.

Al grabar se revisa cada audio: duración, volumen (muy bajo) y saturación (muy alto),
para repetirlo en el momento si salió mal. Todo queda en `data/` de este PC: nunca va a Git.
"""

import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050
PHRASES_FILE = Path("training/voz/frases.txt")
MIN_SECONDS = 0.8
MAX_SECONDS = 15.0
# Pico por debajo de esto: el micrófono quedó lejos o muy bajo.
QUIET_PEAK = 0.08
# Si más del 0,1 % de las muestras tocan el tope, la voz se saturó (suena rota).
CLIP_LEVEL = 0.99
CLIP_SHARE = 0.001
# Lo que se considera silencio al recortar los bordes.
SILENCE = 0.02
EDGE_PAD_SECONDS = 0.15

README = """Grabaciones para entrenar una voz propia de Piper (JARVIS).

- wavs/: un WAV por frase, mono, 22 050 Hz, 16 bits.
- metadata.csv: archivo|texto, separado por "|".

Cómo entrenar: training/notebooks/jarvis_voz_piper.ipynb (Google Colab) y
docs/mejoras-v1.md, sección "Crear una voz propia".
"""


class DatasetError(ValueError):
    """La grabación no sirve (vacía, muy corta, muy baja…): el mensaje dice por qué."""


@dataclass(frozen=True)
class ClipReport:
    index: int
    seconds: float
    peak: float
    warnings: list[str]


def load_phrases(path: Path = PHRASES_FILE) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _default_decoder(data: bytes) -> np.ndarray:
    """Cualquier audio del navegador (webm, ogg, mp4, wav) → float32 mono a 22 050 Hz."""
    from faster_whisper import decode_audio

    return decode_audio(io.BytesIO(data), sampling_rate=SAMPLE_RATE)


def trim_silence(audio: np.ndarray) -> np.ndarray:
    """Quita el silencio del comienzo y del final, dejando un margen corto."""
    loud = np.flatnonzero(np.abs(audio) > SILENCE)
    if loud.size == 0:
        return audio[:0]
    pad = int(EDGE_PAD_SECONDS * SAMPLE_RATE)
    return audio[max(0, loud[0] - pad) : loud[-1] + pad]


def check_clip(audio: np.ndarray) -> list[str]:
    """Problemas que se pueden corregir repitiendo la grabación (o vacía si está bien)."""
    seconds = audio.size / SAMPLE_RATE
    if seconds < MIN_SECONDS:
        raise DatasetError("No se oyó la frase: acérquese un poco al micrófono y repítala.")
    if seconds > MAX_SECONDS:
        raise DatasetError(f"La grabación supera {MAX_SECONDS:.0f} s: grabe sólo la frase.")
    warnings = []
    peak = float(np.max(np.abs(audio)))
    if peak < QUIET_PEAK:
        warnings.append("Se oye muy bajo: acérquese al micrófono o suba su volumen.")
    if float(np.mean(np.abs(audio) >= CLIP_LEVEL)) > CLIP_SHARE:
        warnings.append("Se saturó (sonó muy fuerte): aléjese un poco del micrófono.")
    return warnings


def to_wav(audio: np.ndarray) -> bytes:
    out = io.BytesIO()
    import wave

    with wave.open(out, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(SAMPLE_RATE)
        target.writeframes((np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
    return out.getvalue()


def clip_name(index: int) -> str:
    return f"frase_{index:04d}.wav"


class VoiceDataset:
    def __init__(
        self,
        root: Path,
        phrases: list[str] | None = None,
        decoder: Callable[[bytes], np.ndarray] | None = None,
    ) -> None:
        self.root = root
        self.wavs = root / "wavs"
        self.phrases = load_phrases() if phrases is None else phrases
        self._decode = decoder or _default_decoder

    # ---------- Frases ----------

    def phrase(self, index: int) -> str:
        if not 1 <= index <= len(self.phrases):
            raise DatasetError("Esa frase no existe.")
        return self.phrases[index - 1]

    def recorded(self) -> list[int]:
        if not self.wavs.exists():
            return []
        found = []
        for path in self.wavs.glob("frase_*.wav"):
            try:
                index = int(path.stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            if 1 <= index <= len(self.phrases):
                found.append(index)
        return sorted(found)

    def next_pending(self) -> int | None:
        done = set(self.recorded())
        return next((i for i in range(1, len(self.phrases) + 1) if i not in done), None)

    def overview(self) -> dict:
        done = self.recorded()
        seconds = sum(self._seconds(i) for i in done)
        return {
            "total": len(self.phrases),
            "recorded": len(done),
            "minutes": round(seconds / 60, 2),
            "next": self.next_pending(),
            "folder": str(self.root),
        }

    def _seconds(self, index: int) -> float:
        size = (self.wavs / clip_name(index)).stat().st_size
        return max(0, size - 44) / (2 * SAMPLE_RATE)

    # ---------- Grabaciones ----------

    def save(self, index: int, data: bytes) -> ClipReport:
        self.phrase(index)  # que la frase exista
        if not data:
            raise DatasetError("La grabación llegó vacía.")
        try:
            audio = self._decode(data)
        except Exception as exc:
            raise DatasetError("No se pudo leer la grabación. Inténtelo otra vez.") from exc
        audio = trim_silence(np.asarray(audio, dtype=np.float32))
        warnings = check_clip(audio)
        self.wavs.mkdir(parents=True, exist_ok=True)
        (self.wavs / clip_name(index)).write_bytes(to_wav(audio))
        self.write_metadata()
        return ClipReport(
            index=index,
            seconds=round(audio.size / SAMPLE_RATE, 2),
            peak=round(float(np.max(np.abs(audio))), 2),
            warnings=warnings,
        )

    def audio(self, index: int) -> bytes:
        path = self.wavs / clip_name(index)
        if not path.exists():
            raise DatasetError("Esa frase todavía no está grabada.")
        return path.read_bytes()

    def remove(self, index: int) -> None:
        (self.wavs / clip_name(index)).unlink(missing_ok=True)
        self.write_metadata()

    def write_metadata(self) -> None:
        lines = [f"{clip_name(i)}|{self.phrase(i)}" for i in self.recorded()]
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "metadata.csv").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n"
        )

    def export_zip(self) -> bytes:
        """Todo lo grabado, listo para subir al cuaderno de entrenamiento."""
        done = self.recorded()
        if not done:
            raise DatasetError("Todavía no hay frases grabadas.")
        self.write_metadata()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("voz-propia/LEEME.txt", README)
            archive.write(self.root / "metadata.csv", "voz-propia/metadata.csv")
            for index in done:
                archive.write(self.wavs / clip_name(index), f"voz-propia/wavs/{clip_name(index)}")
        return out.getvalue()
