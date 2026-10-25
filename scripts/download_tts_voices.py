"""Descarga las voces en español para texto a voz (una sola vez).

    .venv\\Scripts\\python -m scripts.download_tts_voices
Quedan en data/tts/ (no se suben a Git). Fuentes:
- Piper: https://huggingface.co/rhasspy/piper-voices (licencias en cada MODEL_CARD)
- Kokoro: https://github.com/thewh1teagle/kokoro-onnx/releases (Apache 2.0)
"""

import json
import sys
from pathlib import Path

import httpx

TTS_DIR = Path("data/tts")
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es"
PIPER_VOICES = {
    "es_MX-claude-high": "es_MX/claude/high",
    "es_MX-ald-medium": "es_MX/ald/medium",
    "es_ES-davefx-medium": "es_ES/davefx/medium",
    "es_AR-daniela-high": "es_AR/daniela/high",
}
KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_FILES = ["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"]


def download(client: httpx.Client, url: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 0:
        print(f"= ya existe {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        done = 0
        with partial.open("wb") as file:
            for chunk in response.iter_bytes(1 << 20):
                file.write(chunk)
                done += len(chunk)
                if total:
                    sys.stdout.write(f"\r  {target.name}: {done * 100 // total} %")
                    sys.stdout.flush()
    partial.rename(target)
    print(f"\r+ {target} ({done / 1e6:.0f} MB)")


def fix_piper_config(path: Path) -> None:
    """Algunas voces viejas guardan `phoneme_type` como "PhonemeType.ESPEAK" (un error del
    exportador) o no lo declaran, y piper-tts 1.3 falla al cargarlas."""
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("phoneme_type") not in ("espeak", "text", "pinyin"):
        config["phoneme_type"] = "espeak"
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  (corregido phoneme_type en {path.name})")


def main() -> None:
    with httpx.Client(timeout=600) as client:
        for name, path in PIPER_VOICES.items():
            for suffix in (".onnx", ".onnx.json"):
                download(
                    client,
                    f"{PIPER_BASE}/{path}/{name}{suffix}",
                    TTS_DIR / "piper" / f"{name}{suffix}",
                )
            fix_piper_config(TTS_DIR / "piper" / f"{name}.onnx.json")
        for filename in KOKORO_FILES:
            download(client, f"{KOKORO_BASE}/{filename}", TTS_DIR / "kokoro" / filename)


if __name__ == "__main__":
    main()
