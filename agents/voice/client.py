"""Habla con la API de JARVIS: transcribir (Whisper small) y conversar (WebSocket con voz)."""

import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import websockets

# Sin noticias de la API durante este tiempo = algo falló: se avisa y se sigue escuchando.
RECV_TIMEOUT = 90


class JarvisClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", token: str | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._ws_url = self._base.replace("http", "ws", 1) + "/ws/chat"
        self._notices_url = self._base.replace("http", "ws", 1) + "/ws/avisos"
        # Con el inicio de sesión (Etapa 11), el agente entra con el token de data/agent.token.
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.AsyncClient(base_url=self._base, timeout=120, headers=self._headers)

    async def close(self) -> None:
        await self._http.aclose()

    async def healthy(self) -> bool:
        try:
            return (await self._http.get("/health")).status_code == 200
        except httpx.HTTPError:
            return False

    async def warm(self, prefill: bool = False) -> dict[str, bool]:
        """Pide a la API dejar cargados Whisper, la voz y el modelo de chat."""
        response = await self._http.post("/api/voice/warm", params={"prefill": prefill})
        response.raise_for_status()
        return response.json()

    async def speak(self, text: str) -> bytes:
        """WAV con la voz de JARVIS (para frases fijas como "Un momento, lo consulto")."""
        response = await self._http.post("/api/voice/speak", json={"text": text})
        response.raise_for_status()
        return response.content

    async def notices(self) -> AsyncIterator[dict[str, Any]]:
        """Avisos en vivo (recordatorios vencidos del dueño). Se corta si la API se apaga."""
        async with websockets.connect(self._notices_url, additional_headers=self._headers) as ws:
            while True:
                yield json.loads(await ws.recv())

    async def set_status(self, state: str, text: str = "") -> None:
        """Avisa a la pantalla qué está haciendo el agente (si falla, no importa)."""
        with contextlib.suppress(httpx.HTTPError):
            await self._http.put("/api/voice/agent", json={"state": state, "text": text[:500]})

    async def transcribe(self, wav: bytes) -> str:
        response = await self._http.post(
            "/api/voice/transcribe", files={"audio": ("voz.wav", wav, "audio/wav")}
        )
        response.raise_for_status()
        return response.json()["text"]

    async def chat(self, text: str, conversation_id: int | None) -> AsyncIterator[dict[str, Any]]:
        """Eventos del chat con voz. Los de tipo "audio" traen `wav` (bytes) ya decodificado."""
        async with websockets.connect(
            self._ws_url, max_size=2**24, additional_headers=self._headers
        ) as ws:
            payload = {"message": text, "conversation_id": conversation_id, "voice": True}
            await ws.send(json.dumps(payload))
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), RECV_TIMEOUT))
                if event["type"] == "audio":
                    event["wav"] = base64.b64decode(event.pop("audio"))
                yield event
                if event["type"] in ("audio_end", "error"):
                    return
