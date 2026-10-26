"""¿La frase empieza llamando a JARVIS?

Dos detectores (ver docs/etapas/09-jarvis-siempre-atento.md):

- `WhisperNameDetector` (por defecto): transcribe los primeros 2,5 s con Whisper `base`
  y busca "Jarvis" entre las primeras palabras. Con "Yarbis" dicho en español:
  7/7 aciertos y 0/12 falsas alarmas.
- `OpenWakeWordDetector`: modelo `hey_jarvis` de openWakeWord. Muy bueno con el nombre
  en inglés ("Jarvis", "Hey Jarvis": 0,99); con pronunciación española casi 0.
"""

import re
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from app.services.stt_service import normalize_name

SAMPLE_RATE = 16000
_NAME = re.compile(r"\bjarvis\b", re.IGNORECASE)
_CALL_WORDS = 4  # el nombre tiene que estar al principio: "Jarvis, …", "Hola Jarvis, …"


def mentions_name_at_start(text: str, words: int = _CALL_WORDS) -> bool:
    """ "Hola Jarvis, ¿qué hora es?" → sí. "¿Qué puerto usa la base de JARVIS?" → no."""
    first = " ".join(normalize_name(text).split()[:words])
    return bool(_NAME.search(first))


@dataclass(frozen=True)
class Detection:
    called: bool
    text: str = ""
    score: float = 0.0


class NameDetector(Protocol):
    def detect(self, audio: np.ndarray) -> Detection: ...


class WhisperNameDetector:
    def __init__(
        self,
        model: str = "base",
        threads: int = 4,
        prompt: str = "Jarvis (se pronuncia Yarbis).",
        seconds: float = 2.5,
        pad_seconds: float = 0.5,
        model_factory: Any = None,
    ) -> None:
        self._prompt = prompt
        self._seconds = seconds
        self._pad = pad_seconds
        if model_factory is not None:
            self._model = model_factory()
        else:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                model, device="cpu", compute_type="int8", cpu_threads=threads
            )

    def detect(self, audio: np.ndarray) -> Detection:
        start = audio[: int(SAMPLE_RATE * self._seconds)].astype(np.float32) / 32768
        # Medio segundo de silencio antes: sin él, Whisper a veces se come la primera palabra.
        padded = np.concatenate([np.zeros(int(SAMPLE_RATE * self._pad), np.float32), start])
        segments, _ = self._model.transcribe(
            padded,
            language="es",
            beam_size=1,
            initial_prompt=self._prompt,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return Detection(called=mentions_name_at_start(text), text=text)


class OpenWakeWordDetector:
    """Para quien diga el nombre con pronunciación inglesa."""

    def __init__(self, threshold: float = 0.5, model: Any = None) -> None:
        if model is None:
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            download_models(["hey_jarvis"])
            model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        self._model = model
        self._threshold = threshold

    def detect(self, audio: np.ndarray) -> Detection:
        self._model.reset()
        best = 0.0
        padded = np.concatenate([np.zeros(SAMPLE_RATE // 2, np.int16), audio.astype(np.int16)])
        for i in range(0, len(padded) - 1280, 1280):
            best = max(best, float(self._model.predict(padded[i : i + 1280])["hey_jarvis"]))
        return Detection(called=best >= self._threshold, score=best)


class AnyDetector:
    """Llamado si cualquiera de los detectores lo detecta (el rápido primero)."""

    def __init__(self, *detectors: NameDetector) -> None:
        self._detectors = detectors

    def detect(self, audio: np.ndarray) -> Detection:
        last = Detection(called=False)
        for detector in self._detectors:
            last = detector.detect(audio)
            if last.called:
                return last
        return last
