"""Pruebas de voz a texto con un Whisper falso (rápidas, sin descargar modelos)."""

from types import SimpleNamespace

import httpx
import pytest

from app.core.dependencies import get_stt
from app.main import create_app
from app.services.stt_service import (
    FasterWhisperSTT,
    Transcription,
    TranscriptionError,
    WhisperSettings,
)
from tests.fakes import as_owner

pytestmark = pytest.mark.anyio


class FakeWhisperModel:
    def __init__(self, text: str = " Hola JARVIS. ", duration: float = 2.5, fail: bool = False):
        self.text = text
        self.duration = duration
        self.fail = fail
        self.calls: list[dict] = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise ValueError("Invalid data found when processing input")
        segments = [SimpleNamespace(text=part) for part in self.text.split("|")]
        return iter(segments), SimpleNamespace(language="es", duration=self.duration)


def make_stt(model: FakeWhisperModel, **settings) -> tuple[FasterWhisperSTT, list]:
    created: list = []

    def factory(cfg: WhisperSettings) -> FakeWhisperModel:
        created.append(cfg)
        return model

    return FasterWhisperSTT(WhisperSettings(**settings), model_factory=factory), created


# ---------- Servicio ----------


async def test_transcribe_y_une_los_segmentos():
    model = FakeWhisperModel(" ¿Qué hora | es? ")
    stt, _ = make_stt(model)
    result = await stt.transcribe(b"audio")

    assert result.text == "¿Qué hora es?"
    assert result.language == "es" and result.audio_seconds == 2.5


async def test_usa_idioma_pista_y_filtro_de_silencios():
    model = FakeWhisperModel()
    stt, _ = make_stt(model, language="es", initial_prompt="Habla con JARVIS")
    await stt.transcribe(b"audio")

    call = model.calls[0]
    assert call["language"] == "es"
    assert call["initial_prompt"] == "Habla con JARVIS"
    assert call["vad_filter"] is True and call["beam_size"] == 1


async def test_carga_el_modelo_una_sola_vez_y_solo_cuando_se_usa():
    stt, created = make_stt(FakeWhisperModel())
    assert not stt.loaded and created == []

    await stt.transcribe(b"uno")
    await stt.transcribe(b"dos")
    assert stt.loaded and len(created) == 1


async def test_se_descarga_por_inactividad():
    stt, created = make_stt(FakeWhisperModel(), idle_unload_seconds=0)
    await stt.transcribe(b"audio")
    assert stt.unload_if_idle() is True and not stt.loaded

    await stt.transcribe(b"audio")
    assert len(created) == 2


async def test_no_descarga_si_se_uso_hace_poco():
    stt, _ = make_stt(FakeWhisperModel(), idle_unload_seconds=300)
    await stt.transcribe(b"audio")
    assert stt.unload_if_idle() is False and stt.loaded


@pytest.mark.parametrize(
    ("model", "audio", "error"),
    [
        (FakeWhisperModel(), b"", "vacío"),
        (FakeWhisperModel(fail=True), b"basura", "No se pudo leer"),
        (FakeWhisperModel(duration=90), b"largo", "60 segundos"),
    ],
)
async def test_errores_claros(model, audio: bytes, error: str):
    stt, _ = make_stt(model)
    with pytest.raises(TranscriptionError, match=error):
        await stt.transcribe(audio)


# ---------- Endpoint ----------


class StubSTT:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.received: list[bytes] = []

    async def transcribe(self, audio: bytes) -> Transcription:
        self.received.append(audio)
        if self.fail:
            raise TranscriptionError("No se pudo leer el audio")
        return Transcription(
            text="Hola JARVIS", language="es", audio_seconds=1.5, processing_seconds=0.8
        )


def client_with(stt: StubSTT) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_stt] = lambda: stt
    as_owner(app)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_endpoint_devuelve_el_texto():
    stt = StubSTT()
    async with client_with(stt) as client:
        response = await client.post(
            "/api/voice/transcribe", files={"audio": ("voz.webm", b"OggS...", "audio/webm")}
        )
    assert response.status_code == 200
    assert response.json() == {
        "text": "Hola JARVIS",
        "language": "es",
        "audio_seconds": 1.5,
        "processing_seconds": 0.8,
    }
    assert stt.received == [b"OggS..."]


async def test_endpoint_rechaza_audio_vacio_y_danado():
    async with client_with(StubSTT()) as client:
        empty = await client.post(
            "/api/voice/transcribe", files={"audio": ("v.webm", b"", "audio/webm")}
        )
        assert empty.status_code == 400
    async with client_with(StubSTT(fail=True)) as client:
        broken = await client.post(
            "/api/voice/transcribe", files={"audio": ("v.webm", b"x", "audio/webm")}
        )
        assert broken.status_code == 422


async def test_la_pagina_de_chat_tiene_el_microfono():
    async with client_with(StubSTT()) as client:
        html = (await client.get("/")).text
    assert 'id="mic"' in html and "/static/js/voice.js" in html


# ---------- El nombre: "Yarbis" se escribe "Jarvis" ----------


@pytest.mark.parametrize(
    ("heard", "fixed"),
    [
        ("Yarbis, ¿cómo estás?", "Jarvis, ¿cómo estás?"),
        ("hola harvis", "hola Jarvis"),
        ("Oye Yarvis, apaga eso", "Oye Jarvis, apaga eso"),
        ("gracias llarvis", "gracias Jarvis"),
        ("Un jarabe para la tos", "Un jarabe para la tos"),
    ],
)
def test_corrige_como_suena_el_nombre(heard: str, fixed: str):
    from app.services.stt_service import normalize_name

    assert normalize_name(heard) == fixed


async def test_la_transcripcion_sale_con_el_nombre_corregido():
    stt, _ = make_stt(FakeWhisperModel(" Yarbis, ¿qué hora es? "))
    assert (await stt.transcribe(b"audio")).text == "Jarvis, ¿qué hora es?"


# ---------- Textos inventados (INC-03: se activaba solo) ----------

PROMPT = WhisperSettings().initial_prompt


@pytest.mark.parametrize(
    "text",
    [
        "Jarvis, el asistente de la casa.",  # lo que se vio en pantalla
        "También se pronuncia Yarbis, el asistente de la casa.",
        "En el canal de subtítulos en español, el asistente de la casa se pronuncia Yarbis.",
        "¡Suscríbete!",
    ],
)
def test_descarta_lo_que_whisper_inventa(text: str):
    from app.services.stt_service import invented

    assert invented(SimpleNamespace(text=text, no_speech_prob=0.0, avg_logprob=0.0), PROMPT)


@pytest.mark.parametrize(
    "text",
    [
        "Jarvis, apaga las luces de la casa.",
        "Jarvis, ¿qué me recomiendas para la cena?",
        "Jarvis, ¿cómo se pronuncia croissant?",
        "Jarvis, ¿quién es el asistente de voz más famoso?",
        "Gracias Jarvis, eso es todo por hoy.",
    ],
)
def test_no_descarta_frases_reales(text: str):
    from app.services.stt_service import invented

    segment = SimpleNamespace(text=text, no_speech_prob=0.01, avg_logprob=-0.25)
    assert invented(segment, PROMPT) is None


def test_descarta_segmentos_que_no_parecen_voz():
    from app.services.stt_service import invented

    def seg(no_speech, logprob):
        return SimpleNamespace(text="Jarvis, sí.", no_speech_prob=no_speech, avg_logprob=logprob)

    assert invented(seg(0.87, -0.5), PROMPT) == "no parece voz"
    assert invented(seg(0.45, -1.0), PROMPT) == "dudoso y poco seguro"
    assert invented(seg(0.45, -0.3), PROMPT) is None  # dudoso pero seguro de las palabras


async def test_la_transcripcion_sale_sin_lo_inventado():
    class HallucinatingModel(FakeWhisperModel):
        def transcribe(self, audio, **kwargs):
            segments = [
                SimpleNamespace(
                    text=" Jarvis, el asistente de la casa.", no_speech_prob=0.5, avg_logprob=-0.9
                ),
            ]
            return iter(segments), SimpleNamespace(language="es", duration=0.4)

    stt, _ = make_stt(HallucinatingModel())
    assert (await stt.transcribe(b"audio")).text == ""  # nada que empiece con "Jarvis"
