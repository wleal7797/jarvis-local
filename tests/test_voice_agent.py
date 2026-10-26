"""Pruebas del agente de voz (sin micrófono ni parlantes: todo simulado)."""

import io
import wave

import numpy as np
import pytest

from agents.voice.agent import VoiceAgent
from agents.voice.conversation import Conversation, ConversationSettings, Mode
from agents.voice.player import Player, decode_wav, tone
from agents.voice.segmenter import FRAME_SAMPLES, SegmenterSettings, UtteranceSegmenter
from agents.voice.wake import Detection, mentions_name_at_start

pytestmark = pytest.mark.anyio

FRAME = np.ones(FRAME_SAMPLES, dtype=np.int16)


# ---------- Segmentador ----------


def feed_pattern(segmenter, pattern: str):
    """'.' = silencio, '#' = voz (cada carácter es un cuadro de 30 ms)."""
    out = []
    for char in pattern:
        result = segmenter.feed(FRAME, 0.9 if char == "#" else 0.05)
        if result is not None:
            out.append(result)
    return out


def test_entrega_la_frase_cuando_hay_silencio_suficiente():
    segmenter = UtteranceSegmenter(SegmenterSettings(end_silence_ms=300, preroll_ms=90))
    utterances = feed_pattern(segmenter, "....." + "#" * 20 + "." * 10)
    assert len(utterances) == 1
    # 3 cuadros previos + 20 de voz + 10 de silencio
    assert len(utterances[0]) == (3 + 20 + 10) * FRAME_SAMPLES


def test_las_pausas_cortas_no_cortan_la_frase():
    segmenter = UtteranceSegmenter(SegmenterSettings(end_silence_ms=300))
    assert len(feed_pattern(segmenter, "#" * 10 + "." * 5 + "#" * 10 + "." * 12)) == 1


def test_ignora_ruidos_muy_cortos():
    segmenter = UtteranceSegmenter(SegmenterSettings(end_silence_ms=300, min_speech_ms=250))
    assert feed_pattern(segmenter, "..##" + "." * 15) == []


def test_corta_frases_demasiado_largas():
    segmenter = UtteranceSegmenter(SegmenterSettings(max_utterance_ms=600))
    assert len(feed_pattern(segmenter, "#" * 25)) == 1


# ---------- ¿Lo llamaron? ----------


@pytest.mark.parametrize(
    ("text", "called"),
    [
        ("Jarvis, ¿cómo estás?", True),
        ("Hola Jarvis, ¿qué hora es?", True),
        ("Oye, Yarbis, apaga eso", True),  # se corrige a Jarvis
        ("¿Qué puerto usa la base de datos de JARVIS?", False),  # habla de él, no lo llama
        ("Pon música tranquila", False),
    ],
)
def test_reconoce_el_nombre_al_principio(text: str, called: bool):
    assert mentions_name_at_start(text) is called


# ---------- Estado de la conversación ----------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_modo_conversacion_no_pide_el_nombre_unos_segundos():
    clock = Clock()
    conv = Conversation(ConversationSettings(follow_up_seconds=8), clock=clock)
    assert conv.needs_name()

    conv.attending()
    conv.speaking("Buenas tardes.")
    assert conv.needs_name()  # mientras habla, sólo con el nombre se le interrumpe
    conv.finished_speaking()
    clock.now += 5
    assert not conv.needs_name() and conv.mode == Mode.ESCUCHANDO
    clock.now += 4
    assert conv.needs_name() and conv.mode == Mode.DORMIDO


def test_la_conversacion_se_reinicia_tras_cinco_minutos():
    clock = Clock()
    conv = Conversation(ConversationSettings(session_minutes=5), clock=clock)
    conv.started_conversation(7)
    conv.attending()
    clock.now += 301
    conv.needs_name()
    assert conv.conversation_id is None


def test_reconoce_su_propia_voz_como_eco():
    conv = Conversation()
    conv.speaking("Bogotá está a dos mil seiscientos metros de altura.")
    assert conv.is_echo("bogotá está a dos mil seiscientos metros")
    assert not conv.is_echo("Jarvis, para por favor")


# ---------- Agente ----------


def wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 2205)
    return buffer.getvalue()


class FakeDetector:
    def __init__(self, called: bool, text: str = "Jarvis, hola") -> None:
        self.result = Detection(called=called, text=text)
        self.calls = 0

    def detect(self, audio):
        self.calls += 1
        return self.result


class FakeClient:
    def __init__(self, text: str = "Jarvis, ¿cómo estás?") -> None:
        self.text = text
        self.sent: list[tuple[str, int | None]] = []
        self.transcribed = 0

    async def transcribe(self, wav: bytes) -> str:
        self.transcribed += 1
        return self.text

    async def chat(self, text, conversation_id):
        self.sent.append((text, conversation_id))
        yield {"type": "start", "conversation_id": 42}
        yield {"type": "token", "content": "Muy bien, gracias."}
        yield {"type": "audio", "wav": wav_bytes(), "text": "Muy bien, gracias."}
        yield {"type": "audio_end"}


class FakePlayer:
    def __init__(self, playing: bool = False) -> None:
        self.playing = playing
        self.queued: list[str] = []
        self.chimes = 0
        self.stopped = 0

    def enqueue(self, wav: bytes, sentence: str = "") -> None:
        self.queued.append(sentence)

    def chime(self, *_args) -> None:
        self.chimes += 1

    def stop(self) -> None:
        self.stopped += 1
        self.playing = False


UTTERANCE = np.zeros(16000, dtype=np.int16)


class Notes:
    def __init__(self) -> None:
        self.states: list[str] = []

    def __call__(self, state: str, text: str = "") -> None:
        self.states.append(state)


async def test_si_no_lo_llaman_no_envia_nada():
    client = FakeClient("Pon música tranquila")
    agent = VoiceAgent(None, client, FakePlayer())
    assert await agent.handle(UTTERANCE) == "ignorada"
    assert client.sent == []


async def test_lo_llaman_transcribe_una_sola_vez_responde_y_habla():
    client, player, notes = FakeClient(), FakePlayer(), Notes()
    agent = VoiceAgent(None, client, player, notify=notes)

    assert await agent.handle(UTTERANCE) == "respondida"
    assert client.transcribed == 1  # la misma transcripción sirve para el nombre y el chat
    assert client.sent == [("Jarvis, ¿cómo estás?", None)]
    assert player.chimes == 1 and player.queued == ["Muy bien, gracias."]
    assert agent.conversation.conversation_id == 42
    assert notes.states == ["pensando", "hablando", "atento"]


async def test_en_modo_conversacion_no_hace_falta_el_nombre():
    client, notes = FakeClient("¿Y mañana?"), Notes()
    agent = VoiceAgent(None, client, FakePlayer(), notify=notes)
    agent.conversation.started_conversation(42)
    agent.conversation.finished_speaking()  # acaba de responder: escuchando

    assert await agent.handle(UTTERANCE) == "respondida"
    assert client.sent == [("¿Y mañana?", 42)]  # sigue la misma conversación
    assert notes.states[:2] == ["escuchando", "pensando"]


async def test_mientras_busca_en_documentos_lo_dice_y_lo_muestra():
    class SearchingClient(FakeClient):
        async def chat(self, text, conversation_id):
            yield {"type": "start", "conversation_id": 7}
            yield {"type": "searching"}
            yield {"type": "audio", "wav": wav_bytes(), "text": "Gabriel García Márquez."}
            yield {"type": "audio_end"}

    player, notes = FakePlayer(), Notes()
    client = SearchingClient("Jarvis, ¿quién escribió Cien años de soledad?")
    agent = VoiceAgent(None, client, player, notify=notes, searching_wav=wav_bytes())
    assert await agent.handle(UTTERANCE) == "respondida"
    assert player.queued == ["Un momento, lo consulto.", "Gabriel García Márquez."]
    assert notes.states == ["pensando", "buscando", "hablando", "atento"]


async def test_al_terminar_la_frase_de_espera_sigue_atendiendo():
    agent = VoiceAgent(None, FakeClient(), FakePlayer())
    agent.conversation.attending()
    async with agent._busy:  # la respuesta todavía no llega
        agent.on_player_idle()
    assert agent.conversation.mode == Mode.ATENDIENDO


async def test_openwakeword_detecta_y_luego_transcribe():
    detector, client = FakeDetector(called=True), FakeClient("Hey Jarvis, la hora")
    agent = VoiceAgent(detector, client, FakePlayer(), name_from_text=False)
    assert await agent.handle(UTTERANCE) == "respondida"
    assert detector.calls == 1 and client.transcribed == 1


async def test_solo_openwakeword_no_mira_la_transcripcion():
    client = FakeClient("Jarvis, ¿cómo estás?")
    agent = VoiceAgent(FakeDetector(called=False), client, FakePlayer(), name_from_text=False)
    assert await agent.handle(UTTERANCE) == "ignorada"
    assert client.transcribed == 0


async def test_ambos_detectores_si_openwakeword_falla_mira_el_texto():
    client = FakeClient("Yarbis, ¿cómo estás?")
    agent = VoiceAgent(FakeDetector(called=False), client, FakePlayer(), name_from_text=True)
    assert await agent.handle(UTTERANCE) == "respondida"


async def test_interrumpirlo_diciendo_su_nombre():
    player = FakePlayer(playing=True)
    agent = VoiceAgent(None, FakeClient("Jarvis, espera"), player)
    agent.conversation.speaking("Le cuento una historia muy larga sobre el café.")

    assert await agent.handle(UTTERANCE) == "respondida"
    assert player.stopped == 1


async def test_su_propia_voz_no_lo_interrumpe():
    player = FakePlayer(playing=True)
    sentence = "Soy Jarvis y estoy aquí para ayudarle con lo que necesite."
    agent = VoiceAgent(None, FakeClient(sentence), player)
    agent.conversation.speaking(sentence)

    assert await agent.handle(UTTERANCE) == "eco"
    assert player.stopped == 0


async def test_transcripcion_vacia_avisa_con_un_sonido():
    player = FakePlayer()
    agent = VoiceAgent(FakeDetector(called=True), FakeClient(text=""), player, name_from_text=False)
    assert await agent.handle(UTTERANCE) == "vacía"
    assert player.chimes == 2  # "le escucho" + "no entendí"


async def test_un_solo_agente_a_la_vez():
    from agents.voice.__main__ import single_instance_lock

    first = single_instance_lock(port=8798)  # otro puerto: el agente real puede estar encendido
    try:
        assert first is not None
        assert single_instance_lock(port=8798) is None
    finally:
        if first:
            first.close()


# ---------- Reproductor ----------


class FakeSoundDevice:
    def __init__(self) -> None:
        self.played: list[int] = []
        self.stops = 0

    def play(self, audio, rate, device=None):
        self.played.append(len(audio))

    def stop(self):
        self.stops += 1


def test_reproduce_en_orden_y_avisa_al_terminar():
    import threading

    idle = threading.Event()
    started: list[str] = []
    backend = FakeSoundDevice()
    player = Player(on_start=started.append, on_idle=idle.set, backend=backend)
    player.enqueue(wav_bytes(), "Uno.")
    player.enqueue(wav_bytes(), "Dos.")
    assert idle.wait(3)
    assert started == ["Uno.", "Dos."] and len(backend.played) == 2
    player.close()


def test_utilidades_de_audio():
    audio, rate = decode_wav(wav_bytes())
    assert rate == 22050 and len(audio) == 2205
    chime = tone([440, 880], note_ms=50)
    assert chime.dtype == np.int16 and len(chime) == 2 * int(22050 * 0.05)
