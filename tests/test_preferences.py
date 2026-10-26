"""Preferencias guardadas desde la app y endpoint de ajustes de voz."""

from types import SimpleNamespace

import httpx
import pytest

from app.core.dependencies import get_current_user, get_tts
from app.core.preferences import load_preferences, save_preferences
from app.main import create_app
from app.services.tts_service import PiperSettings, PiperTTS

pytestmark = pytest.mark.anyio


def test_guardar_y_leer_preferencias(tmp_path):
    path = tmp_path / "preferences.json"
    assert load_preferences(path) == {}
    save_preferences({"tts_voice": "a"}, path)
    save_preferences({"tts_length_scale": 1.1}, path)
    assert load_preferences(path) == {"tts_voice": "a", "tts_length_scale": 1.1}


def test_archivo_danado_se_ignora(tmp_path):
    path = tmp_path / "preferences.json"
    path.write_text("{no es json", encoding="utf-8")
    assert load_preferences(path) == {}


async def test_endpoint_de_ajustes_de_voz(tmp_path, monkeypatch):
    for name in ("es_ES-davefx-medium", "es_MX-claude-high"):
        (tmp_path / f"{name}.onnx").write_bytes(b"x")
    saved: list[dict] = []
    monkeypatch.setattr(
        "app.controllers.voice_controller.save_preferences", lambda updates: saved.append(updates)
    )
    tts = PiperTTS(PiperSettings(voices_dir=str(tmp_path), voice="es_ES-davefx-medium"))
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[get_tts] = lambda: tts
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        current = (await client.get("/api/voice/settings")).json()
        assert current["voice"] == "es_ES-davefx-medium" and len(current["installed"]) == 2

        changed = await client.put(
            "/api/voice/settings", json={"voice": "es_MX-claude-high", "length_scale": 1.15}
        )
        assert changed.status_code == 200
        assert changed.json()["voice"] == "es_MX-claude-high"
        assert saved == [
            {"tts_voice": "es_MX-claude-high", "tts_length_scale": 1.15, "tts_effect": "ninguno"}
        ]

        missing = await client.put("/api/voice/settings", json={"voice": "no-existe"})
        assert missing.status_code == 422
