"""Habla con la API de JARVIS: transcribir (Whisper small) y conversar (WebSocket con voz)."""

import base64
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import websockets


class JarvisClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000") -> None:
        self._base = base_url.rstrip("/")
        self._ws_url = self._base.replace("http", "ws", 1) + "/ws/chat"
        self._http = httpx.AsyncClient(base_url=self._base, timeout=120)

    async def close(self) -> None:
        await self._http.aclose()

    async def healthy(self) -> bool:
        try:
            return (await self._http.get("/health")).status_code == 200
        except httpx.HTTPError:
            return False

    async def warm_up(self) -> None:
        """Pide transcribir 1 s de silencio: la API carga Whisper y queda lista."""
        import io
        import wave

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 16000)
        with contextlib.suppress(httpx.HTTPError):
            await self.transcribe(buffer.getvalue())

    async def transcribe(self, wav: bytes) -> str:
        response = await self._http.post(
            "/api/voice/transcribe", files={"audio": ("voz.wav", wav, "audio/wav")}
        )
        response.raise_for_status()
        return response.json()["text"]

    async def chat(self, text: str, conversation_id: int | None) -> AsyncIterator[dict[str, Any]]:
        """Eventos del chat con voz. Los de tipo "audio" traen `wav` (bytes) ya decodificado."""
        async with websockets.connect(self._ws_url, max_size=2**24) as ws:
            payload = {"message": text, "conversation_id": conversation_id, "voice": True}
            await ws.send(json.dumps(payload))
            while True:
                event = json.loads(await ws.recv())
                if event["type"] == "audio":
                    event["wav"] = base64.b64decode(event.pop("audio"))
                yield event
                if event["type"] in ("audio_end", "error"):
                    return
