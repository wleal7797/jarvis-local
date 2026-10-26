"""Agente de voz de JARVIS: micrófono siempre activo en el PC.

    .venv\\Scripts\\python -m agents.voice                 # di "Jarvis, …"
    .venv\\Scripts\\python -m agents.voice --dispositivos  # ver micrófonos y parlantes
    .venv\\Scripts\\python -m agents.voice --detector ambos   # también "Jarvis" en inglés
    .venv\\Scripts\\python -m agents.voice --simular a.wav b.wav --mudo   # sin micrófono

Requiere la API encendida (.\\scripts\\jarvis.ps1 iniciar). La frase sólo sale del
micrófono hacia la API si empieza con "Jarvis" o si están conversando; todo queda en el PC.
"""

import argparse
import asyncio
import logging

import numpy as np

from agents.voice.agent import VoiceAgent, status
from agents.voice.client import JarvisClient
from agents.voice.conversation import Conversation, ConversationSettings, Mode
from agents.voice.player import Player
from agents.voice.segmenter import FRAME_SAMPLES, SAMPLE_RATE, UtteranceSegmenter
from agents.voice.wake import AnyDetector, OpenWakeWordDetector, WhisperNameDetector
from app.core.config import get_settings
from app.core.logging import setup_logging

logger = logging.getLogger("jarvis.voz")

# Mientras él habla, el micrófono oye los parlantes: se exige más certeza de que es voz humana.
THRESHOLD_IDLE = 0.5
THRESHOLD_WHILE_SPEAKING = 0.8


def build_detector(kind: str):
    if kind == "openwakeword":
        return OpenWakeWordDetector()
    if kind == "ambos":
        return AnyDetector(OpenWakeWordDetector(), WhisperNameDetector())
    return WhisperNameDetector()


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

    status("Cargando detector de nombre, filtro de voz y Whisper de la API…")
    # Precarga Whisper small en la API: así la primera frase no espera ~5 s a que cargue.
    warmup = asyncio.create_task(client.warm_up())
    download_models(["hey_jarvis"])  # modelos base de openWakeWord (incluye Silero VAD)
    vad = VAD()
    detector = await asyncio.to_thread(build_detector, args.detector)
    conversation = Conversation(ConversationSettings(follow_up_seconds=args.seguir))
    await warmup
    loop = asyncio.get_running_loop()
    agent: VoiceAgent | None = None

    def on_idle() -> None:
        if agent is not None:
            loop.call_soon_threadsafe(agent.on_player_idle)

    player = Player(
        on_idle=on_idle,
        output_device=args.parlantes,
        backend=SilentBackend() if args.mudo else None,
    )
    agent = VoiceAgent(detector, client, player, conversation)
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
        utterance = segmenter.feed(frame, float(vad.predict(frame)))
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
    args = parser.parse_args()
    if args.dispositivos:
        list_devices()
        return
    setup_logging("WARNING")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        status("Agente de voz detenido.")


if __name__ == "__main__":
    main()
