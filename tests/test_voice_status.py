"""Pruebas de lo que hace más ágil la voz: estado en pantalla, precarga y respuestas cortas."""

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import (
    get_llm,
    get_stt,
    get_tts,
    get_voice_status,
)
from app.main import create_app
from app.services.prompt_builder import SPOKEN_INSTRUCTIONS, build_messages
from app.services.stt_service import FasterWhisperSTT, WhisperSettings
from app.services.voice_status import VoiceStatusHub
from tests.fakes import FakeLLM, as_owner

# ---------- Estado del agente ----------


def test_el_estado_llega_a_los_suscritos_y_al_que_entra_despues():
    hub = VoiceStatusHub()
    queue = hub.subscribe()
    assert queue.get_nowait().state == "apagado"  # al suscribirse recibe el actual

    hub.publish("pensando", "¿Qué hora es?")
    update = queue.get_nowait()
    assert (update.state, update.text) == ("pensando", "¿Qué hora es?")
    assert hub.subscribe().get_nowait().state == "pensando"


def test_estado_desconocido_es_error_y_un_navegador_lento_no_frena():
    hub = VoiceStatusHub(queue_size=1)
    with pytest.raises(ValueError):
        hub.publish("bailando")
    hub.subscribe()  # su cola ya está llena con el estado inicial
    hub.publish("escuchando")  # no se bloquea ni falla


class WarmStub:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.warmed = 0

    def warm(self) -> None:
        self.warmed += 1
        if self.fail:
            raise RuntimeError("sin GPU")


def app_client(hub=None, stt=None, tts=None, llm=None) -> TestClient:
    app = create_app()
    as_owner(app)
    app.dependency_overrides[get_voice_status] = lambda: hub or VoiceStatusHub()
    app.dependency_overrides[get_stt] = lambda: stt or WarmStub()
    app.dependency_overrides[get_tts] = lambda: tts or WarmStub()
    app.dependency_overrides[get_llm] = lambda: llm or FakeLLM()
    return TestClient(app)


def test_el_agente_avisa_y_el_navegador_lo_recibe_al_instante():
    hub = VoiceStatusHub()
    client = app_client(hub)
    with client.websocket_connect("/ws/voice-status") as ws:
        assert ws.receive_json()["state"] == "apagado"
        response = client.put("/api/voice/agent", json={"state": "pensando", "text": "Hola"})
        assert response.status_code == 200
        update = ws.receive_json()
        assert (update["state"], update["text"]) == ("pensando", "Hola")
    assert client.get("/api/voice/agent").json()["state"] == "pensando"
    assert client.put("/api/voice/agent", json={"state": "bailando"}).status_code == 422


def test_precarga_whisper_voz_y_modelo_aunque_uno_falle():
    stt, tts, llm = WarmStub(fail=True), WarmStub(), FakeLLM()
    response = app_client(stt=stt, tts=tts, llm=llm).post("/api/voice/warm?prefill=true")
    assert response.status_code == 200
    assert response.json() == {"stt": False, "tts": True, "llm": True}
    assert stt.warmed == tts.warmed == 1 and llm.warmed == "10m" and llm.prefilled


def test_la_pagina_muestra_lo_que_hace_el_agente():
    html = app_client().get("/").text
    assert 'id="agent-status"' in html and "/static/js/agent-status.js" in html


# ---------- Respuestas habladas cortas ----------


def test_por_voz_pide_respuestas_breves_sin_tocar_el_historial():
    spoken = build_messages([], "¿Quién pintó la Mona Lisa?", spoken=True)
    assert spoken[-1].content.startswith("¿Quién pintó la Mona Lisa?")
    assert spoken[-1].content.endswith(SPOKEN_INSTRUCTIONS)
    assert build_messages([], "Hola")[-1].content == "Hola"


# ---------- Whisper en la GPU ----------


def test_whisper_vuelve_a_la_cpu_si_la_gpu_falla(monkeypatch):
    from app.services import stt_service

    devices: list[str] = []

    def fake_load(cfg, device):
        devices.append(device)
        if device == "cuda":
            raise RuntimeError("Library cublas64_12.dll is not found")
        return "modelo-cpu"

    monkeypatch.setattr(stt_service, "_load_whisper", fake_load)
    assert stt_service._default_factory(WhisperSettings(device="auto")) == "modelo-cpu"
    assert devices == ["cuda", "cpu"]

    devices.clear()
    assert stt_service._default_factory(WhisperSettings(device="cpu")) == "modelo-cpu"
    assert devices == ["cpu"]


def test_warm_carga_una_vez_y_reinicia_la_inactividad():
    loads: list[WhisperSettings] = []
    stt = FasterWhisperSTT(WhisperSettings(), model_factory=lambda cfg: loads.append(cfg) or "m")
    stt.warm()
    stt.warm()
    assert stt.loaded and len(loads) == 1
    assert not stt.unload_if_idle()  # se acaba de usar
