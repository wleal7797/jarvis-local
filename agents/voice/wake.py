"""¿La frase empieza llamando a JARVIS?

- Por defecto se busca "Jarvis" entre las primeras palabras de la transcripción que hace
  Whisper `small` en la API (en la GPU, ~0,5 s). Antes había un Whisper `base` aparte sólo
  para el nombre (1,7 s) y luego se transcribía otra vez: ahora es una sola pasada.
- `OpenWakeWordDetector`: modelo `hey_jarvis` de openWakeWord, instantáneo y muy bueno con
  el nombre en inglés ("Jarvis", "Hey Jarvis": 0,99); con pronunciación española casi 0.
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
