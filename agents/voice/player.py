"""Reproduce la voz de JARVIS por los parlantes del PC, frase por frase, y se calla al instante.

Corre en su propio hilo: el micrófono sigue escuchando mientras habla (para poder
interrumpirlo diciendo "Jarvis").
"""

import io
import logging
import queue
import threading
import time
import wave
from collections.abc import Callable

import numpy as np

logger = logging.getLogger(__name__)


def decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())
        return np.frombuffer(frames, dtype=np.int16), wav_file.getframerate()


def tone(
    frequencies: list[float], note_ms: int = 90, rate: int = 22050, volume: float = 0.25
) -> np.ndarray:
    """Un sonido corto (por ejemplo, el "te escucho" al oír su nombre)."""
    notes = []
    for frequency in frequencies:
        t = np.arange(int(rate * note_ms / 1000)) / rate
        envelope = np.minimum(1, np.minimum(t, t[::-1]) * 60)  # sin chasquidos
        notes.append(np.sin(2 * np.pi * frequency * t) * envelope * volume)
    return (np.concatenate(notes) * 32767).astype(np.int16)


CHIME_LISTENING = tone([660, 880])
CHIME_ERROR = tone([440, 330], note_ms=140)


class Player:
    def __init__(
        self,
        on_start: Callable[[str], None] | None = None,
        on_idle: Callable[[], None] | None = None,
        output_device: int | str | None = None,
        backend=None,
    ) -> None:
        if backend is None:
            import sounddevice as backend  # noqa: N813
        self._sd = backend
        self._device = output_device
        self._queue: queue.Queue[tuple[np.ndarray, int, str] | None] = queue.Queue()
        self._stop = threading.Event()
        self._playing = threading.Event()
        self._on_start = on_start or (lambda _sentence: None)
        self._on_idle = on_idle or (lambda: None)
        self._thread = threading.Thread(target=self._run, name="jarvis-player", daemon=True)
        self._thread.start()

    @property
    def playing(self) -> bool:
        return self._playing.is_set() or not self._queue.empty()

    def enqueue(self, wav: bytes, sentence: str = "") -> None:
        audio, rate = decode_wav(wav)
        self._queue.put((audio, rate, sentence))

    def chime(self, audio: np.ndarray = CHIME_LISTENING, rate: int = 22050) -> None:
        """Suena ya, sin esperar la cola (aviso inmediato de "te escucho")."""
        try:
            self._sd.play(audio, rate, device=self._device)
        except Exception as exc:  # sin parlantes no es motivo para caerse
            logger.warning("no se pudo reproducir el aviso", extra={"error": str(exc)})

    def stop(self) -> None:
        """Se calla de inmediato y descarta lo que faltaba por decir."""
        self._stop.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._sd.stop()

    def close(self) -> None:
        self.stop()
        self._queue.put(None)

    def _run(self) -> None:
        while (item := self._queue.get()) is not None:
            audio, rate, sentence = item
            self._stop.clear()
            self._playing.set()
            self._on_start(sentence)
            try:
                self._sd.play(audio, rate, device=self._device)
                duration = len(audio) / rate
                started = time.monotonic()
                while time.monotonic() - started < duration + 0.05 and not self._stop.is_set():
                    time.sleep(0.03)
            except Exception as exc:
                logger.warning("no se pudo reproducir", extra={"error": str(exc)})
            finally:
                self._playing.clear()
            if self._queue.empty():
                self._on_idle()
