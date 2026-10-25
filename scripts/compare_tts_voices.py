"""Genera la misma frase con varias voces (Piper y Kokoro) para elegir escuchando.

    .venv\Scripts\python -m pip install -e ".[voces]"     # Kokoro, sólo para comparar
    .venv\Scripts\python -m scripts.download_tts_voices
    .venv\Scripts\python -m scripts.compare_tts_voices
Resultado: data/tts/samples/voces-jarvis.html (ábrelo en el navegador y escucha).
"""

import base64
import html
import io
import time
import wave
from pathlib import Path

import numpy as np
from kokoro_onnx import Kokoro
from piper import PiperVoice

TEXT = (
    "Buenas tardes. Soy Jarvis, su asistente personal. La base de datos escucha en el "
    "puerto 5434, y en Bogotá hoy hace dieciocho grados. ¿En qué más puedo ayudarle?"
)
PIPER = [
    ("es_MX-claude-high", "Hombre · México"),
    ("es_MX-ald-medium", "Hombre · México"),
    ("es_ES-davefx-medium", "Hombre · España"),
    ("es_AR-daniela-high", "Mujer · Argentina"),
]
KOKORO = [
    ("em_alex", "Hombre · neutro"),
    ("em_santa", "Hombre · neutro"),
    ("ef_dora", "Mujer · neutra"),
]
OUT = Path("data/tts/samples")


def to_wav(samples: np.ndarray, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return buffer.getvalue()


def duration(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


def main() -> None:
    results = []
    for name, label in PIPER:
        voice = PiperVoice.load(f"data/tts/piper/{name}.onnx")
        buffer = io.BytesIO()
        started = time.perf_counter()
        with wave.open(buffer, "wb") as wav_file:
            voice.synthesize_wav(TEXT, wav_file)
        results.append(("Piper", name, label, time.perf_counter() - started, buffer.getvalue()))
    kokoro = Kokoro("data/tts/kokoro/kokoro-v1.0.int8.onnx", "data/tts/kokoro/voices-v1.0.bin")
    for name, label in KOKORO:
        started = time.perf_counter()
        samples, rate = kokoro.create(TEXT, voice=name, speed=1.0, lang="es")
        results.append(
            ("Kokoro", name, label, time.perf_counter() - started, to_wav(samples, rate))
        )

    OUT.mkdir(parents=True, exist_ok=True)
    cards = []
    for i, (engine, name, label, seconds, data) in enumerate(results, 1):
        rtf = seconds / duration(data)
        print(f"{i}. {engine} {name}: {seconds:.2f} s para {duration(data):.1f} s (RTF {rtf:.2f})")
        audio = base64.b64encode(data).decode()
        cards.append(
            f"<article><h2>{i}. {engine} · {html.escape(name)}</h2><p>{label} · RTF {rtf:.2f}</p>"
            f'<audio controls src="data:audio/wav;base64,{audio}"></audio></article>'
        )
    page = (
        '<!doctype html><meta charset="utf-8"><title>Voces para JARVIS</title>'
        "<style>body{font:15px system-ui;max-width:680px;margin:auto;padding:16px}"
        "article{border:1px solid #ccc;border-radius:12px;padding:12px;margin:10px 0}"
        "audio{width:100%}</style>"
        f"<h1>Voces para JARVIS</h1><blockquote>{html.escape(TEXT)}</blockquote>{''.join(cards)}"
    )
    (OUT / "voces-jarvis.html").write_text(page, encoding="utf-8")
    print(f"Abre {OUT / 'voces-jarvis.html'}")


if __name__ == "__main__":
    main()
