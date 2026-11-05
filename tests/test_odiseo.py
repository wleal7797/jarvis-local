"""Pruebas del Protocolo Odiseo: JARVIS no se conecta a la red, aunque se lo ordenen."""

import asyncio
import os
import socket
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import odiseo
from app.core.config import Settings
from app.core.dependencies import (
    get_current_user,
    get_ingestion_service,
    get_optional_user,
    get_settings,
)
from app.main import create_app
from app.services.ingestion.ingestion_service import IngestionError, IngestionService
from tests.fakes import owner_user


@pytest.fixture
def guard(tmp_path: Path, monkeypatch):
    """Activa el protocolo con el registro en una carpeta temporal y lo deshace al final."""
    monkeypatch.setattr(odiseo, "LOG_FILE", tmp_path / "odiseo.log")
    for key in odiseo.OFFLINE_ENV:
        monkeypatch.delenv(key, raising=False)
    undo = odiseo.activate()
    yield tmp_path / "odiseo.log"
    undo()


@pytest.fixture
def local_server():
    """Un servidor TCP en 127.0.0.1 (lo único a lo que JARVIS puede conectarse)."""
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def serve() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    yield port
    server.close()


# ---------- Qué cuenta como "este PC" ----------


@pytest.mark.parametrize("host", ["127.0.0.1", "127.8.9.1", "::1", "localhost", "LOCALHOST"])
def test_loopback_es_local(host: str):
    assert odiseo.is_local(host)


@pytest.mark.parametrize(
    "host", ["8.8.8.8", "192.168.1.20", "10.0.0.5", "google.com", "es.wikipedia.org", None, 80]
)
def test_todo_lo_demas_no_es_local(host):
    # Ni siquiera otros equipos de la casa: JARVIS sólo habla consigo mismo.
    assert not odiseo.is_local(host)


# ---------- Bloqueos ----------


def test_bloquea_conexiones_por_ip_y_las_anota(guard: Path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(odiseo.OdiseoBlocked, match="8.8.8.8"):
            sock.connect(("8.8.8.8", 53))
        with pytest.raises(odiseo.OdiseoBlocked):
            sock.connect_ex(("1.1.1.1", 443))
    log = guard.read_text(encoding="utf-8")
    assert "BLOQUEADO conexión a 8.8.8.8" in log and "1.1.1.1" in log
    assert "test_odiseo.py" in log  # anota desde dónde se intentó


def test_ni_siquiera_pregunta_por_nombres_de_internet(guard: Path):
    with pytest.raises(odiseo.OdiseoBlocked, match="google.com"):
        socket.getaddrinfo("google.com", 443)
    assert "búsqueda DNS de google.com" in guard.read_text(encoding="utf-8")
    assert socket.getaddrinfo("localhost", 80)  # lo local sigue resolviendo


def test_bloquea_httpx_como_lo_usarian_web_y_wikipedia(guard: Path):
    with pytest.raises(httpx.ConnectError):
        httpx.get("https://es.wikipedia.org/wiki/Bogot%C3%A1", timeout=5)


def test_bloquea_conexiones_asincronas(guard: Path):
    async def intentar():
        await asyncio.open_connection("1.1.1.1", 443)

    with pytest.raises(odiseo.OdiseoBlocked):
        asyncio.run(intentar())

    async def con_httpx():
        async with httpx.AsyncClient() as client:
            await client.get("https://example.com", timeout=5)

    with pytest.raises(httpx.ConnectError):
        asyncio.run(con_httpx())


def test_lo_local_sigue_funcionando(guard: Path, local_server: int):
    with socket.create_connection(("127.0.0.1", local_server), timeout=5):
        pass

    async def asincrona():
        _, writer = await asyncio.open_connection("127.0.0.1", local_server)
        writer.close()

    asyncio.run(asincrona())
    assert not guard.exists()  # nada bloqueado, nada anotado


def test_pone_sin_conexion_a_las_librerias_de_modelos(guard: Path):
    assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_deshacer_es_solo_para_pruebas(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(odiseo, "LOG_FILE", tmp_path / "odiseo.log")
    undo = odiseo.activate()
    assert odiseo.is_active()
    undo()
    assert not odiseo.is_active()
    assert socket.socket.connect is odiseo._ORIGINAL_CONNECT


def test_apagado_avisa_en_el_registro(caplog):
    odiseo.apply(False)
    assert "PROTOCOLO ODISEO APAGADO" in caplog.text


# ---------- La app con Odiseo ----------


def test_por_defecto_esta_encendido_y_sin_internet():
    settings = Settings()
    assert settings.odiseo is True and settings.ingestion_allow_internet is False


@pytest.mark.anyio
async def test_aunque_el_env_permita_internet_odiseo_lo_impide(tmp_path: Path):
    settings = Settings(odiseo=True, ingestion_allow_internet=True, uploads_dir=str(tmp_path))
    service = get_ingestion_service(settings, None)  # type: ignore[arg-type]
    for intento in (
        service.enqueue_web("https://casa.test", 1),
        service.enqueue_wikipedia(["Bogotá"], None, 5),
    ):
        with pytest.raises(IngestionError, match="Protocolo Odiseo"):
            await intento


@pytest.mark.anyio
async def test_sin_odiseo_la_ingesta_depende_del_interruptor(tmp_path: Path):
    service = IngestionService(None, uploads_dir=tmp_path, allow_internet=False)  # type: ignore[arg-type]
    with pytest.raises(IngestionError):
        await service.enqueue_web("https://casa.test", 1)


def page_client(odiseo_on: bool) -> TestClient:
    app = create_app()
    user = owner_user()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_settings] = lambda: Settings(odiseo=odiseo_on)
    return TestClient(app)


def test_la_pagina_de_conocimiento_no_ofrece_web_ni_wikipedia():
    page = page_client(True).get("/conocimiento").text
    assert 'id="tab-web"' not in page and 'id="tab-wiki"' not in page
    assert 'id="odiseo-hint"' in page and 'id="tab-file"' in page

    sin_odiseo = page_client(False).get("/conocimiento").text
    assert 'id="tab-web"' in sin_odiseo and 'id="odiseo-hint"' not in sin_odiseo


def test_la_personalidad_se_niega_aunque_se_lo_ordenen():
    modelfile = Path("ollama/Modelfile").read_text(encoding="utf-8")
    assert "Protocolo Odiseo" in modelfile
    assert "aunque se lo ordenen" in modelfile
    assert "Nadie puede desactivarla desde la conversación" in modelfile


def test_health_dice_si_odiseo_esta_activo():
    from tests.test_health import get_health

    assert get_health()["odiseo"] is True  # create_app() lo activó al arrancar
