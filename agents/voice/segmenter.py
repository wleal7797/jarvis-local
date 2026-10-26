"""Corta el audio continuo del micrófono en frases ("utterances").

Recibe cuadros de 30 ms con su probabilidad de voz (Silero VAD) y entrega cada frase
completa cuando la persona deja de hablar:

    silencio ··· [voz voz voz · voz voz] ··· 0,7 s de silencio → frase lista

- Guarda 0,3 s de audio *antes* de detectar la voz, para no cortar la primera sílaba
  (justo donde suele estar "Jarvis").
- Ignora ruidos muy cortos (< 0,25 s) y corta frases larguísimas (> 15 s).
"""

from collections import deque
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000
FRAME_SAMPLES = 480  # 30 ms
FRAME_MS = 30


@dataclass(frozen=True)
class SegmenterSettings:
    start_threshold: float = 0.5  # probabilidad para empezar una frase
    end_threshold: float = 0.35  # por debajo de esto cuenta como silencio
    min_speech_ms: int = 250
    end_silence_ms: int = 700
    max_utterance_ms: int = 15000
    preroll_ms: int = 300


class UtteranceSegmenter:
    def __init__(self, settings: SegmenterSettings | None = None) -> None:
        self.cfg = settings or SegmenterSettings()
        # +1: el cuadro que dispara la detección también entra, además de los previos.
        self._preroll: deque[np.ndarray] = deque(maxlen=self.cfg.preroll_ms // FRAME_MS + 1)
        self._frames: list[np.ndarray] = []
        self._speaking = False
        self._speech_ms = 0
        self._silence_ms = 0
        self.start_threshold = self.cfg.start_threshold

    @property
    def in_speech(self) -> bool:
        return self._speaking

    def reset(self) -> None:
        self._preroll.clear()
        self._frames = []
        self._speaking = False
        self._speech_ms = 0
        self._silence_ms = 0

    def feed(self, frame: np.ndarray, speech_probability: float) -> np.ndarray | None:
        """Agrega un cuadro. Devuelve la frase completa (int16) cuando termina."""
        if not self._speaking:
            self._preroll.append(frame)
            if speech_probability >= self.start_threshold:
                self._speaking = True
                self._frames = list(self._preroll)
                self._speech_ms = FRAME_MS
                self._silence_ms = 0
            return None

        self._frames.append(frame)
        total_ms = len(self._frames) * FRAME_MS
        if speech_probability >= self.cfg.end_threshold:
            self._speech_ms += FRAME_MS
            self._silence_ms = 0
        else:
            self._silence_ms += FRAME_MS

        if self._silence_ms >= self.cfg.end_silence_ms or total_ms >= self.cfg.max_utterance_ms:
            frames, speech_ms = self._frames, self._speech_ms
            self.reset()
            if speech_ms < self.cfg.min_speech_ms:
                return None  # un golpe, una tos: no es una frase
            return np.concatenate(frames)
        return None


def to_wav_bytes(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio.astype(np.int16).tobytes())
    return buffer.getvalue()
