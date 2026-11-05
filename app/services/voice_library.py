"""Voces propias (mejora adicional a la V1): subir una voz de Piper desde la app.

Una voz de Piper son **dos archivos** con el mismo nombre:
- `<nombre>.onnx`       el modelo (la voz en sí, 20–120 MB)
- `<nombre>.onnx.json`  su configuración (idioma, frecuencia de muestreo, fonemas)

Antes de instalarla se prueba de verdad: se carga y se le hace decir una frase. Si falla,
no se instala nada. Las voces subidas quedan en `data/tts/piper/` (nunca va a Git) y se
marcan como `"jarvis_subida": true` para poder quitarlas sin tocar las descargadas.
"""

import json
import re
import shutil
import tempfile
import unicodedata
import wave
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

MAX_MODEL_BYTES = 300 * 1024 * 1024  # las voces "high" de Piper pesan ~115 MB
MAX_CONFIG_BYTES = 1024 * 1024
MIN_MODEL_BYTES = 1024 * 1024
CUSTOM_MARK = "jarvis_subida"
TEST_PHRASE = "Hola, soy Jarvis."
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{2,59}$")


class VoiceUploadError(ValueError):
    """La voz no se pudo instalar (formato, tamaño, nombre o no funciona)."""


def clean_name(raw: str) -> str:
    """'Mi Voz (abuela).onnx' → 'mi-voz-abuela'."""
    stem = raw.strip()
    for suffix in (".onnx.json", ".json", ".onnx"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    plain = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode().lower()
    plain = re.sub(r"[^a-z0-9_-]+", "-", plain).strip("-_")
    if not _NAME.match(plain):
        raise VoiceUploadError(
            "El nombre debe tener entre 3 y 60 letras, números, guiones o guiones bajos."
        )
    return plain


def read_config(data: bytes) -> dict[str, Any]:
    """Valida el .onnx.json de Piper y corrige el `phoneme_type` de voces viejas."""
    try:
        config = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise VoiceUploadError("El archivo .json no es un JSON válido.") from None
    if not isinstance(config, dict):
        raise VoiceUploadError("El archivo .json no es una configuración de Piper.")
    sample_rate = (config.get("audio") or {}).get("sample_rate")
    if not isinstance(sample_rate, int) or not isinstance(config.get("phoneme_id_map"), dict):
        raise VoiceUploadError(
            "El .json no parece de Piper: le falta audio.sample_rate o phoneme_id_map."
        )
    if config.get("phoneme_type") not in ("espeak", "text", "pinyin"):
        config["phoneme_type"] = "espeak"  # mismo arreglo que scripts/download_tts_voices
    return config


def _copy_limited(source: BinaryIO, target: Path, limit: int, what: str) -> int:
    """Copia por partes (no carga 100 MB en la RAM) y se detiene si pasa el límite."""
    written = 0
    with target.open("wb") as out:
        while chunk := source.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                raise VoiceUploadError(f"{what} supera {limit // (1024 * 1024)} MB.")
            out.write(chunk)
    return written


def _default_tester(model: Path) -> float:
    """Carga la voz y le hace decir una frase. Devuelve los segundos de audio."""
    from piper import PiperVoice

    voice = PiperVoice.load(str(model))
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(TEST_PHRASE, wav_file)
    with wave.open(BytesIO(buffer.getvalue())) as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


class VoiceLibrary:
    def __init__(
        self, voices_dir: str | Path, tester: Callable[[Path], float] | None = None
    ) -> None:
        self._dir = Path(voices_dir)
        self._tester = tester

    def _test(self, model: Path) -> float:
        return (self._tester or _default_tester)(model)

    def exists(self, name: str) -> bool:
        return (self._dir / f"{name}.onnx").exists()

    def is_custom(self, name: str) -> bool:
        config = self._dir / f"{name}.onnx.json"
        try:
            return bool(json.loads(config.read_text(encoding="utf-8")).get(CUSTOM_MARK))
        except (OSError, json.JSONDecodeError):
            return False

    def install(self, name: str, model: BinaryIO, config: bytes) -> dict[str, Any]:
        """Prueba la voz en una carpeta temporal y, si funciona, la instala."""
        name = clean_name(name)
        if self.exists(name):
            raise VoiceUploadError(f"Ya hay una voz llamada «{name}». Use otro nombre.")
        if len(config) > MAX_CONFIG_BYTES:
            raise VoiceUploadError("El archivo .json es demasiado grande.")
        settings = read_config(config)
        settings[CUSTOM_MARK] = True
        self._dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._dir) as tmp:
            trial_model = Path(tmp) / f"{name}.onnx"
            size = _copy_limited(model, trial_model, MAX_MODEL_BYTES, "El modelo .onnx")
            if size < MIN_MODEL_BYTES:
                raise VoiceUploadError("El archivo .onnx es demasiado pequeño para ser una voz.")
            trial_config = Path(tmp) / f"{name}.onnx.json"
            trial_config.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
            try:
                seconds = self._test(trial_model)
            except Exception as exc:
                raise VoiceUploadError(
                    "La voz no funcionó al probarla: ¿el .onnx y el .json son de la misma voz? "
                    f"({str(exc)[:120]})"
                ) from None
            if seconds <= 0:
                raise VoiceUploadError("La voz no produjo sonido al probarla.")
            shutil.move(str(trial_config), self._dir / f"{name}.onnx.json")
            shutil.move(str(trial_model), self._dir / f"{name}.onnx")
        return {"name": name, "test_seconds": round(seconds, 2), "size_mb": round(size / 2**20, 1)}

    def remove(self, name: str, active: str) -> None:
        if name == active:
            raise VoiceUploadError(
                "Es la voz que JARVIS está usando: elija otra antes de quitarla."
            )
        if not self.exists(name) or not self.is_custom(name):
            raise VoiceUploadError("Sólo se pueden quitar las voces subidas desde la app.")
        (self._dir / f"{name}.onnx").unlink(missing_ok=True)
        (self._dir / f"{name}.onnx.json").unlink(missing_ok=True)
