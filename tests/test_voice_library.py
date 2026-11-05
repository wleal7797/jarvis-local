"""Pruebas de las voces propias (mejora adicional a la V1)."""

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import get_current_user, get_optional_user, get_settings
from app.main import create_app
from app.services import voice_library
from app.services.tts_service import PiperSettings, PiperTTS
from app.services.voice_library import VoiceLibrary, VoiceUploadError, clean_name, read_config
from tests.fakes import owner_user

CONFIG = {"audio": {"sample_rate": 22050, "quality": "medium"}, "phoneme_id_map": {"a": [1]}}
MODEL = b"\x08\x07" * (600 * 1024)  # ~1,2 MB: pasa el mínimo de tamaño


def config_bytes(**extra) -> bytes:
    return json.dumps({**CONFIG, **extra}).encode("utf-8")


def library(tmp_path: Path, seconds: float = 1.2, fail: bool = False) -> VoiceLibrary:
    def tester(model: Path) -> float:
        assert model.exists() and model.with_suffix(".onnx.json").exists()
        if fail:
            raise RuntimeError("onnx inválido")
        return seconds

    return VoiceLibrary(tmp_path, tester=tester)


# ---------- Nombre y formato ----------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("es_CO-mivoz-medium.onnx", "es_co-mivoz-medium"),
        ("Mi Voz (abuela).onnx.json", "mi-voz-abuela"),
        ("  Narrador Ñandú ", "narrador-nandu"),
    ],
)
def test_limpia_el_nombre_de_la_voz(raw: str, clean: str):
    assert clean_name(raw) == clean


@pytest.mark.parametrize("raw", ["", "ab", "..", "!!!"])
def test_nombres_invalidos(raw: str):
    with pytest.raises(VoiceUploadError):
        clean_name(raw)


def test_un_nombre_no_puede_salir_de_la_carpeta_de_voces():
    assert clean_name("../../windows/system32") == "windows-system32"


def test_valida_la_configuracion_de_piper():
    config = read_config(config_bytes(phoneme_type="PhonemeType.ESPEAK"))
    assert config["phoneme_type"] == "espeak"  # corrige el error de voces viejas
    for bad in (b"no es json", b"[1, 2]", json.dumps({"audio": {}}).encode()):
        with pytest.raises(VoiceUploadError):
            read_config(bad)


# ---------- Instalar y quitar ----------


def test_instala_la_voz_sólo_si_funciona(tmp_path: Path):
    result = library(tmp_path).install("Mi Voz", io.BytesIO(MODEL), config_bytes())
    assert result["name"] == "mi-voz" and result["test_seconds"] == 1.2
    assert (tmp_path / "mi-voz.onnx").read_bytes() == MODEL
    saved = json.loads((tmp_path / "mi-voz.onnx.json").read_text(encoding="utf-8"))
    assert saved["jarvis_subida"] is True

    voices = PiperTTS(PiperSettings(voices_dir=str(tmp_path))).installed_voices()
    assert voices == [
        {"name": "mi-voz", "language": "", "speaker": "mi-voz", "quality": "medium", "custom": True}
    ]


def test_si_la_voz_no_funciona_no_queda_nada(tmp_path: Path):
    with pytest.raises(VoiceUploadError, match="no funcionó"):
        library(tmp_path, fail=True).install("rota", io.BytesIO(MODEL), config_bytes())
    assert list(tmp_path.iterdir()) == []  # ni archivos ni carpetas temporales


def test_rechaza_repetidas_pequenas_y_grandes(tmp_path: Path, monkeypatch):
    lib = library(tmp_path)
    lib.install("voz", io.BytesIO(MODEL), config_bytes())
    with pytest.raises(VoiceUploadError, match="Ya hay"):
        lib.install("voz", io.BytesIO(MODEL), config_bytes())
    with pytest.raises(VoiceUploadError, match="pequeño"):
        lib.install("chica", io.BytesIO(b"x" * 100), config_bytes())
    monkeypatch.setattr(voice_library, "MAX_MODEL_BYTES", 1024 * 1024)
    with pytest.raises(VoiceUploadError, match="supera"):
        lib.install("enorme", io.BytesIO(MODEL), config_bytes())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["voz.onnx", "voz.onnx.json"]


def test_solo_se_quitan_las_subidas_y_no_la_que_esta_en_uso(tmp_path: Path):
    lib = library(tmp_path)
    lib.install("propia", io.BytesIO(MODEL), config_bytes())
    (tmp_path / "es_ES-davefx-medium.onnx").write_bytes(MODEL)
    (tmp_path / "es_ES-davefx-medium.onnx.json").write_bytes(config_bytes())

    with pytest.raises(VoiceUploadError, match="usando"):
        lib.remove("propia", active="propia")
    with pytest.raises(VoiceUploadError, match="subidas"):
        lib.remove("es_ES-davefx-medium", active="propia")
    lib.remove("propia", active="es_ES-davefx-medium")
    assert not (tmp_path / "propia.onnx").exists()
    assert (tmp_path / "es_ES-davefx-medium.onnx").exists()


# ---------- Endpoints ----------


def client(tmp_path: Path, role: str = "owner") -> TestClient:
    app = create_app()
    user = owner_user()
    user.role = role
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_settings] = lambda: Settings(tts_voices_dir=str(tmp_path))
    return TestClient(app)


def test_endpoint_sube_la_voz_y_un_familiar_no_puede(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(voice_library, "_default_tester", lambda model: 1.0)
    files = {
        "model": ("es_CO-mivoz-medium.onnx", MODEL, "application/octet-stream"),
        "config": ("es_CO-mivoz-medium.onnx.json", config_bytes(), "application/json"),
    }
    response = client(tmp_path).post("/api/voice/voices", files=files)
    assert response.status_code == 201 and response.json()["name"] == "es_co-mivoz-medium"

    wrong = {"model": ("voz.mp3", b"ID3", "audio/mpeg"), "config": files["config"]}
    assert client(tmp_path).post("/api/voice/voices", files=wrong).status_code == 422
    assert client(tmp_path, role="member").post("/api/voice/voices", files=files).status_code == 403


def test_solo_el_dueno_ve_el_apartado_de_voces_propias(tmp_path: Path):
    assert 'id="voice-upload"' in client(tmp_path).get("/").text
    assert 'id="voice-upload"' not in client(tmp_path, role="member").get("/").text
