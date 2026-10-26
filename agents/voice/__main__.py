"""Agente de voz de JARVIS: micrófono siempre activo en el PC.

    .venv\\Scripts\\python -m agents.voice                 # di "Jarvis, …"
    .venv\\Scripts\\python -m agents.voice --dispositivos  # ver micrófonos y parlantes
    .venv\\Scripts\\python -m agents.voice --detector ambos   # también "Jarvis" en inglés
    .venv\\Scripts\\python -m agents.voice --simular a.wav b.wav --mudo   # sin micrófono
    .venv\\Scripts\\python -m agents.voice --detalle   # ver todo lo que oye (diagnóstico)

Requiere la API encendida (.\\scripts\\jarvis.ps1 iniciar). Cada frase se transcribe en
la API (en este mismo PC) y sólo se responde si empieza con "Jarvis" o si están
conversando; las demás se descartan. Sólo puede correr un agente a la vez.
"""

import argparse
import asyncio
import contextlib
import logging
import socket

import numpy as np

from agents.voice.agent import SEARCHING_PHRASE, VoiceAgent, status
from agents.voice.client import JarvisClient
from agents.voice.conversation import Conversation, ConversationSettings, Mode
from agents.voice.player import Player
from agents.voice.segmenter import FRAME_SAMPLES, SAMPLE_RATE, UtteranceSegmenter
from agents.voice.wake import OpenWakeWordDetector
from app.core.config import get_settings
from app.core.logging import setup_logging

logger = logging.getLogger("jarvis.voz")

# Mientras él habla, el micrófono oye los parlantes: se exige más certeza de que es voz humana.
THRESHOLD_IDLE = 0.5
THRESHOLD_WHILE_SPEAKING = 0.8
# Cada cuánto se le pide a la API mantener los modelos cargados (se descargan a los 5 min).
WARM_EVERY_SECONDS = 240
# Puerto local que sólo sirve de "candado": si ya está ocupado, hay otro agente corriendo.
SINGLE_INSTANCE_PORT = 8799


def build_detector(kind: str):
    """(detector por audio, ¿buscar también el nombre en la transcripción?)"""
    if kind == "openwakeword":
        return OpenWakeWordDetector(), False
    if kind == "ambos":
        return OpenWakeWordDetector(), True
    return None, True


def single_instance_lock(port: int = SINGLE_INSTANCE_PORT) -> socket.socket | None:
    """Dos agentes a la vez oyen y responden todo dos veces (y se esperan uno al otro)."""
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", port))
    except OSError:
        lock.close()
        return None
    return lock


class SilentBackend:
    """Para --mudo: no suena nada, pero respeta los tiempos (como si sonara)."""

    def play(self, audio, rate, device=None):
        pass

    def stop(self):
        pass


async def simulated_microphone(files: list[str], agent, push) -> None:
    """Reproduce archivos WAV (16 kHz) como si fueran el micrófono, a velocidad real.

    Entre un archivo y otro espera a que JARVIS termine de responder y de hablar.
    """
    import wave as wave_module

    silence = np.zeros(FRAME_SAMPLES, dtype=np.int16)
    step = FRAME_SAMPLES / SAMPLE_RATE
    for name in files:
        with wave_module.open(name) as wav_file:
            audio = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
        status(f"[simulación] El micrófono oye: {name}")
        padded = np.concatenate([np.zeros(FRAME_SAMPLES * 10, np.int16), audio])
        for i in range(0, len(padded) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
            push(padded[i : i + FRAME_SAMPLES])
            await asyncio.sleep(step)
        for _ in range(40):  # 1,2 s de silencio para cerrar la frase
            push(silence)
            await asyncio.sleep(step)
        await asyncio.sleep(0.5)
        while agent.busy or agent.player.playing:  # espera la respuesta completa
            push(silence)
            await asyncio.sleep(step)
    status("[simulación] Fin.")


def list_devices() -> None:
    import sounddevice as sd

    print(sd.query_devices())
    default_in, default_out = sd.default.device
    print(f"\nPor defecto: micrófono {default_in} · parlantes {default_out}")


async def run(args: argparse.Namespace) -> None:
    import sounddevice as sd
    from openwakeword.utils import download_models
    from openwakeword.vad import VAD

    settings = get_settings()
    client = JarvisClient(f"http://127.0.0.1:{settings.api_port}")
    if not await client.healthy():
        status("La API no responde. Enciéndela primero: .\\scripts\\jarvis.ps1 iniciar")
        return

    status("Cargando filtro de voz y dejando listos Whisper, la voz y el modelo…")
    # Precarga en la API: así la primera frase no espera a que se carguen los modelos.
    warmup = asyncio.create_task(client.warm(prefill=True))
    download_models(["hey_jarvis"])  # modelos base de openWakeWord (incluye Silero VAD)
    vad = VAD()
    detector, name_from_text = await asyncio.to_thread(build_detector, args.detector)
    conversation = Conversation(ConversationSettings(follow_up_seconds=args.seguir))
    with contextlib.suppress(Exception):
        await warmup
    searching_wav = None
    with contextlib.suppress(Exception):
        searching_wav = await client.speak(SEARCHING_PHRASE)
    loop = asyncio.get_running_loop()
    agent: VoiceAgent | None = None
    background: set[asyncio.Task] = set()
    last_status = ["en_espera", ""]

    def notify(state: str, text: str = "") -> None:
        last_status[:] = [state, text]
        task = loop.create_task(client.set_status(state, text))
        background.add(task)
        task.add_done_callback(background.discard)

    async def keep_warm() -> None:
        while True:
            await asyncio.sleep(WARM_EVERY_SECONDS)
            with contextlib.suppress(Exception):
                await client.warm()
            # Señal de vida: si deja de llegar (agente cerrado a la fuerza), la pantalla
            # lo muestra apagado.
            await client.set_status(*last_status)

    def on_idle() -> None:
        if agent is not None:
            loop.call_soon_threadsafe(agent.on_player_idle)

    player = Player(
        on_idle=on_idle,
        output_device=args.parlantes,
        backend=SilentBackend() if args.mudo else None,
    )
    agent = VoiceAgent(
        detector,
        client,
        player,
        conversation,
        verbose=args.detalle,
        notify=notify,
        name_from_text=name_from_text,
        searching_wav=searching_wav,
    )
    segmenter = UtteranceSegmenter()
    frames: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=500)

    def push(frame: np.ndarray) -> None:
        # Si el procesamiento se atrasa, se descartan cuadros en vez de acumular memoria.
        if not frames.full():
            frames.put_nowait(frame)

    def on_audio(indata, _frames, _time, _status) -> None:
        loop.call_soon_threadsafe(push, indata[:, 0].copy())

    def report(task: asyncio.Task) -> None:
        if args.simular and not task.cancelled() and task.exception() is None:
            status(f"[simulación] Resultado: {task.result()}")

    def process(frame: np.ndarray) -> None:
        # Mientras él habla, el micrófono oye los parlantes: se exige más certeza de voz.
        segmenter.start_threshold = THRESHOLD_WHILE_SPEAKING if player.playing else THRESHOLD_IDLE
        was_speaking = segmenter.in_speech
        utterance = segmenter.feed(frame, float(vad.predict(frame)))
        if args.detalle and segmenter.in_speech and not was_speaking:
            status("   · oigo voz…")
        if utterance is not None:
            # La respuesta corre aparte: el micrófono sigue escuchando (para poder interrumpir).
            asyncio.create_task(agent.handle(utterance)).add_done_callback(report)

    if args.simular:
        simulation = asyncio.create_task(simulated_microphone(args.simular, agent, push))
        while not (simulation.done() and frames.empty()):
            try:
                frame = await asyncio.wait_for(frames.get(), timeout=0.5)
            except TimeoutError:
                continue
            process(frame)
        player.close()
        await client.close()
        return

    status('Listo. Diga "Jarvis, …" (Ctrl+C para salir).')
    notify("en_espera")
    warmer = asyncio.create_task(keep_warm())
    try:
        await listen(args, frames, process, conversation, notify, on_audio, sd)
    finally:
        warmer.cancel()
        await client.set_status("apagado")
        player.close()
        await client.close()


async def listen(args, frames, process, conversation, notify, on_audio, sd) -> None:
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=FRAME_SAMPLES,
        device=args.microfono,
        callback=on_audio,
    ):
        last_mode = None
        while True:
            process(await frames.get())
            conversation.needs_name()  # actualiza el modo si venció la escucha
            if conversation.mode != last_mode and conversation.mode == Mode.DORMIDO:
                status('En espera. Diga "Jarvis, …"')
                notify("en_espera")
            last_mode = conversation.mode


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente de voz de JARVIS")
    parser.add_argument("--dispositivos", action="store_true", help="listar micrófonos y parlantes")
    parser.add_argument("--microfono", type=int, default=None, help="número del micrófono")
    parser.add_argument("--parlantes", type=int, default=None, help="número de los parlantes")
    parser.add_argument(
        "--detector",
        choices=["whisper", "openwakeword", "ambos"],
        default="whisper",
        help='cómo reconocer "Jarvis" (whisper: pronunciación en español)',
    )
    parser.add_argument(
        "--seguir", type=float, default=8.0, help="segundos que sigue escuchando sin el nombre"
    )
    parser.add_argument("--simular", nargs="+", help="usar archivos WAV en vez del micrófono")
    parser.add_argument("--mudo", action="store_true", help="no reproducir sonido")
    parser.add_argument(
        "--detalle", action="store_true", help="mostrar lo que oye aunque no digan su nombre"
    )
    args = parser.parse_args()
    if args.dispositivos:
        list_devices()
        return
    setup_logging("WARNING")
    lock = None if args.simular else single_instance_lock()
    if lock is None and not args.simular:
        status("Ya hay un agente de voz encendido. Apáguelo antes de abrir otro.")
        return
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        status("Agente de voz detenido.")


if __name__ == "__main__":
    main()
