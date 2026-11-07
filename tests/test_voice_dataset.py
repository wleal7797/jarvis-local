"""Pruebas de Grabar mi voz (grabaciones para entrenar una voz propia de Piper)."""

import io
import wave
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import get_current_user, get_optional_user, get_settings
from app.main import create_app
from app.services import voice_dataset
from app.services.voice_dataset import (
    SAMPLE_RATE,
    DatasetError,
    VoiceDataset,
    check_clip,
    load_phrases,
    trim_silence,
)
from tests.fakes import owner_user

PHRASES = ["Buenas noches, todo está en orden.", "¿Desea que le recuerde algo?", "Con gusto."]


def voice(seconds: float = 2.0, level: float = 0.5, silence: float = 0.5) -> np.ndarray:
    """Un tono con silencio antes y después, como una frase grabada."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    tone = (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    pad = np.zeros(int(silence * SAMPLE_RATE), np.float32)
    return np.concatenate([pad, tone, pad])


def dataset(tmp_path: Path, audio: np.ndarray | None = None) -> VoiceDataset:
    clip = voice() if audio is None else audio
    return VoiceDataset(tmp_path / "voz-propia", phrases=PHRASES, decoder=lambda data: clip)


# ---------- Revisión de cada grabación ----------


def test_recorta_el_silencio_de_los_bordes():
    trimmed = trim_silence(voice(seconds=2.0, silence=1.0))
    assert 2.0 <= trimmed.size / SAMPLE_RATE <= 2.4  # la frase + un margen corto


@pytest.mark.parametrize(
    ("audio", "problem"),
    [(voice(seconds=0.3), "No se oyó"), (voice(seconds=16), "supera"), (np.zeros(0), "No se oyó")],
)
def test_rechaza_grabaciones_inservibles(audio: np.ndarray, problem: str):
    with pytest.raises(DatasetError, match=problem):
        check_clip(trim_silence(audio))


def test_avisa_si_esta_muy_bajo_o_saturado():
    assert check_clip(voice(level=0.5)) == []
    assert "muy bajo" in check_clip(voice(level=0.05))[0]
    assert "saturó" in check_clip(np.clip(voice(level=3.0), -1, 1))[0]


# ---------- Guardar, escuchar y borrar ----------


def test_guarda_en_el_formato_de_piper(tmp_path: Path):
    ds = dataset(tmp_path)
    report = ds.save(2, b"webm")
    assert report.index == 2 and report.warnings == []

    with wave.open(io.BytesIO(ds.audio(2))) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 22050)
    metadata = (tmp_path / "voz-propia" / "metadata.csv").read_text(encoding="utf-8")
    assert metadata == "frase_0002.wav|¿Desea que le recuerde algo?\n"

    overview = ds.overview()
    assert overview["recorded"] == 1 and overview["next"] == 1 and overview["minutes"] > 0


def test_repetir_reemplaza_y_borrar_quita_de_la_lista(tmp_path: Path):
    ds = dataset(tmp_path)
    ds.save(1, b"a")
    ds.save(1, b"b")
    ds.save(3, b"c")
    assert ds.recorded() == [1, 3] and ds.next_pending() == 2
    ds.remove(1)
    metadata = (tmp_path / "voz-propia" / "metadata.csv").read_text(encoding="utf-8")
    assert metadata == "frase_0003.wav|Con gusto.\n"


def test_errores_claros(tmp_path: Path):
    ds = dataset(tmp_path)
    with pytest.raises(DatasetError, match="no existe"):
        ds.save(99, b"a")
    with pytest.raises(DatasetError, match="vacía"):
        ds.save(1, b"")
    with pytest.raises(DatasetError, match="todavía no"):
        ds.audio(1)

    def broken(data: bytes) -> np.ndarray:
        raise RuntimeError("formato desconocido")

    with pytest.raises(DatasetError, match="No se pudo leer"):
        VoiceDataset(tmp_path, phrases=PHRASES, decoder=broken).save(1, b"x")


def test_exporta_todo_en_un_zip(tmp_path: Path):
    ds = dataset(tmp_path)
    with pytest.raises(DatasetError, match="Todavía no"):
        ds.export_zip()
    ds.save(1, b"a")
    ds.save(3, b"c")
    with zipfile.ZipFile(io.BytesIO(ds.export_zip())) as archive:
        names = sorted(archive.namelist())
        metadata = archive.read("voz-propia/metadata.csv").decode("utf-8")
    assert names == [
        "voz-propia/LEEME.txt",
        "voz-propia/metadata.csv",
        "voz-propia/wavs/frase_0001.wav",
        "voz-propia/wavs/frase_0003.wav",
    ]
    assert metadata.splitlines() == [
        "frase_0001.wav|Buenas noches, todo está en orden.",
        "frase_0003.wav|Con gusto.",
    ]


# ---------- Las frases ----------


def test_las_frases_del_proyecto_sirven_para_leer():
    phrases = load_phrases()
    assert len(phrases) >= 500
    assert len(set(phrases)) == len(phrases)
    for phrase in phrases:
        assert "|" not in phrase and not any(ch.isdigit() for ch in phrase)
        assert 3 <= len(phrase.split()) <= 20
    text = " ".join(phrases).lower()
    for sound in ("ll", "ñ", "rr", "ch", "z", "j", "qu", "güe"):
        assert sound in text, sound


# ---------- Endpoints y página ----------


def client(tmp_path: Path, role: str = "owner", monkeypatch=None) -> TestClient:
    app = create_app()
    user = owner_user()
    user.role = role
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_settings] = lambda: Settings(
        voice_dataset_dir=str(tmp_path / "voz-propia")
    )
    return TestClient(app)


def test_endpoints_graban_y_exportan(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(voice_dataset, "load_phrases", lambda path=None: PHRASES)
    monkeypatch.setattr(voice_dataset, "_default_decoder", lambda data: voice())
    c = client(tmp_path)

    assert c.get("/api/voice/dataset").json()["total"] == 3
    assert c.get("/api/voice/dataset/phrases/1").json()["text"] == PHRASES[0]
    assert c.get("/api/voice/dataset/phrases/9").status_code == 404

    saved = c.post("/api/voice/dataset/phrases/1", files={"audio": ("f.webm", b"x", "audio/webm")})
    assert saved.status_code == 201 and saved.json()["warnings"] == []
    assert c.get("/api/voice/dataset/phrases/1/audio").headers["content-type"] == "audio/wav"
    assert c.get("/api/voice/dataset/export.zip").content[:2] == b"PK"
    assert c.delete("/api/voice/dataset/phrases/1").status_code == 204
    assert c.get("/api/voice/dataset").json()["recorded"] == 0


def test_solo_el_dueno_graba_y_ve_la_pagina(tmp_path: Path):
    member = client(tmp_path, role="member")
    assert member.get("/api/voice/dataset").status_code == 403
    page = member.get("/grabar-voz", follow_redirects=False)
    assert page.status_code == 303
    assert 'href="/grabar-voz"' not in member.get("/").text

    owner = client(tmp_path)
    assert "Grabar mi voz" in owner.get("/grabar-voz").text
    assert 'href="/grabar-voz"' in owner.get("/").text


# ---------- Cuaderno de entrenamiento ----------


def test_el_cuaderno_esta_al_dia_y_usa_el_formato_de_grabar_mi_voz():
    import json

    from scripts.build_voice_notebook import OUT, build

    saved = json.loads(Path(OUT).read_text(encoding="utf-8"))
    assert saved == json.loads(json.dumps(build(), ensure_ascii=False))  # regenerado
    source = "".join("".join(c["source"]) for c in saved["cells"])
    for needed in (
        "voz-propia/metadata.csv",
        "voz-propia/wavs",
        "piper.train fit",
        "--ckpt_path",
        "export_onnx",
        "rhasspy/piper-checkpoints",
        "Agregar una voz",
    ):
        assert needed in source, needed
