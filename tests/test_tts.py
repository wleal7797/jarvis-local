"""Pruebas de texto a voz: limpieza, frases, Piper simulado, voz en el chat y endpoint."""

import base64
import io
import wave
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_chat_service, get_current_user, get_tts
from app.main import create_app
from app.services.speech_pipeline import stream_with_voice
from app.services.tts_service import (
    PiperSettings,
    PiperTTS,
    SentenceSplitter,
    SpeechAudio,
    SpeechError,
    clean_for_speech,
)

pytestmark = pytest.mark.anyio


# ---------- Limpieza del texto ----------


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("Escucha en el puerto 5434 [1].", "Escucha en el puerto 5434."),
        ("Según [1, 2] es así.", "Según es así."),
        ("**Importante:** usa `pytest`", "Importante: usa pytest"),
        ("## Título\n- uno\n- dos", "Título\nuno\ndos"),
        ("Mira https://ejemplo.com/x ahora", "Mira el enlace en pantalla ahora"),
        ("Soy JARVIS 🤖", "Soy Jarvis"),
    ],
)
def test_limpia_lo_que_no_se_debe_leer(raw: str, spoken: str):
    assert clean_for_speech(raw) == spoken


# ---------- Frases mientras llega el texto ----------


def split_streaming(text: str, step: int = 5) -> list[str]:
    splitter = SentenceSplitter()
    sentences: list[str] = []
    for i in range(0, len(text), step):
        sentences += splitter.feed(text[i : i + step])
    return sentences + splitter.flush()


def test_corta_en_frases_aunque_el_texto_llegue_en_pedazos():
    text = "Claro, con gusto le ayudo. La base de datos usa el puerto 5434. ¿Algo más?"
    # "¿Algo más?" llega al final, cuando la frase anterior ya se envió a hablar:
    # se dice sola (esperar para juntarla sólo retrasaría el audio).
    assert split_streaming(text) == [
        "Claro, con gusto le ayudo.",
        "La base de datos usa el puerto 5434.",
        "¿Algo más?",
    ]


def test_no_corta_decimales_ni_abreviaturas():
    text = "El modelo genera 3.5 tokens por segundo. El Sr. Pérez llegó temprano hoy."
    assert split_streaming(text) == [
        "El modelo genera 3.5 tokens por segundo.",
        "El Sr. Pérez llegó temprano hoy.",
    ]


def test_las_frases_muy_cortas_se_juntan():
    assert split_streaming("Sí. Claro. Ahora mismo lo reviso por usted.") == [
        "Sí. Claro. Ahora mismo lo reviso por usted."
    ]


# ---------- Piper (voz simulada) ----------


class FakeVoice:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.configs: list = []

    def synthesize_wav(self, text, wav_file, syn_config=None):
        self.texts.append(text)
        self.configs.append(syn_config)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 22050)  # 1 s de silencio


def make_tts(voice: FakeVoice, **settings) -> tuple[PiperTTS, list]:
    loads: list = []

    def loader(cfg: PiperSettings) -> FakeVoice:
        loads.append(cfg)
        return voice

    return PiperTTS(PiperSettings(**settings), voice_loader=loader), loads


async def test_genera_wav_con_el_texto_limpio():
    voice = FakeVoice()
    tts, loads = make_tts(voice, length_scale=1.1)
    audio = await tts.synthesize("Hola **mundo** [1].")

    assert voice.texts == ["Hola mundo."]
    assert voice.configs[0].length_scale == 1.1
    assert audio.audio_seconds == 1.0
    with wave.open(io.BytesIO(audio.wav)) as wav_file:
        assert wav_file.getframerate() == 22050
    await tts.synthesize("Otra frase.")
    assert len(loads) == 1  # la voz se carga una sola vez


async def test_texto_vacio_o_solo_citas_es_error():
    tts, _ = make_tts(FakeVoice())
    with pytest.raises(SpeechError):
        await tts.synthesize("[1] [2]")


async def test_voz_inexistente_da_un_error_claro(tmp_path):
    tts = PiperTTS(PiperSettings(voices_dir=str(tmp_path), voice="no-existe"))
    with pytest.raises(SpeechError, match="download_tts_voices"):
        await tts.synthesize("Hola")


async def test_se_descarga_por_inactividad():
    tts, loads = make_tts(FakeVoice(), idle_unload_seconds=0)
    await tts.synthesize("Hola a todos.")
    assert tts.unload_if_idle() and not tts.loaded


# ---------- Voz dentro del chat ----------


class StubTTS:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.spoken: list[str] = []

    async def synthesize(self, text: str) -> SpeechAudio:
        if self.fail:
            raise SpeechError("No se encontró la voz")
        self.spoken.append(text)
        return SpeechAudio(wav=b"RIFF" + text.encode(), audio_seconds=1.0, processing_seconds=0.1)


async def chat_events(*pieces: str):
    yield {"type": "start", "conversation_id": 1, "message_id": 1}
    for piece in pieces:
        yield {"type": "token", "content": piece}
    yield {"type": "end", "message_id": 2}


async def test_habla_frase_por_frase_mientras_llega_el_texto():
    sent: list[dict] = []

    async def send(event: dict) -> None:
        sent.append(event)

    tts = StubTTS()
    pieces = ["Buenas tardes, ", "a su servicio. ", "La base usa ", "el puerto 5434."]
    await stream_with_voice(chat_events(*pieces), tts, send)

    types = [e["type"] for e in sent]
    assert types.count("token") == 4 and types[-1] == "audio_end"
    assert tts.spoken == ["Buenas tardes, a su servicio.", "La base usa el puerto 5434."]
    audios = [e for e in sent if e["type"] == "audio"]
    assert [a["seq"] for a in audios] == [0, 1]
    assert base64.b64decode(audios[0]["audio"]).startswith(b"RIFF")


async def test_si_falla_la_voz_el_texto_llega_igual():
    sent: list[dict] = []

    async def send(event: dict) -> None:
        sent.append(event)

    await stream_with_voice(chat_events("Hola a todos, ", "qué tal."), StubTTS(fail=True), send)
    types = [e["type"] for e in sent]
    assert "end" in types and types.count("audio_error") == 1 and types[-1] == "audio_end"


class StubChat:
    async def ensure_conversation(self, user_id: int, conversation_id: int) -> None:
        return None

    def answer(self, user_id: int, text: str, conversation_id: int | None = None):
        return chat_events("Con mucho gusto, ", "aquí estoy para ayudarle.")


def ws_client(tts: StubTTS) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[get_chat_service] = lambda: StubChat()
    app.dependency_overrides[get_tts] = lambda: tts
    return TestClient(app)


def test_websocket_con_voz_envia_audio():
    tts = StubTTS()
    with ws_client(tts).websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hola", "voice": True})
        events = []
        while not events or events[-1]["type"] != "audio_end":
            events.append(ws.receive_json())
    assert "audio" in [e["type"] for e in events]
    assert tts.spoken == ["Con mucho gusto, aquí estoy para ayudarle."]


def test_websocket_sin_voz_no_genera_audio():
    tts = StubTTS()
    with ws_client(tts).websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "Hola", "voice": False})
        events = []
        while not events or events[-1]["type"] != "end":
            events.append(ws.receive_json())
    assert tts.spoken == [] and "audio" not in [e["type"] for e in events]


# ---------- Endpoint /api/voice/speak ----------


async def test_endpoint_speak_devuelve_wav():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    app.dependency_overrides[get_tts] = lambda: StubTTS()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.post("/api/voice/speak", json={"text": "Hola"})
        empty = await client.post("/api/voice/speak", json={"text": ""})
    assert ok.status_code == 200 and ok.headers["content-type"] == "audio/wav"
    assert ok.content.startswith(b"RIFF") and ok.headers["x-audio-seconds"] == "1.0"
    assert empty.status_code == 422
