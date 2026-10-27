"""Pruebas del inicio de sesión y los roles (Etapa 11), con el inicio de sesión ENCENDIDO."""

import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.core.dependencies import (
    get_auth_service,
    get_embedder,
    get_llm,
    get_memory_service,
    get_session_factory,
    get_settings,
)
from app.main import create_app
from app.services.auth_service import (
    SESSION_COOKIE,
    AuthService,
    hash_password,
    verify_password,
)
from app.services.memory_service import Learned
from tests.fakes import FakeEmbedder, FakeLLM, FakeMemory

pytestmark = pytest.mark.anyio

AGENT_TOKEN = "token-del-agente-de-prueba"
OWNER_PASSWORD = "clave-del-dueno-123"

# ---------- Sin base de datos ----------


def test_argon2_guarda_la_contraseña_cifrada():
    stored = hash_password("una clave segura")
    assert stored.startswith("$argon2id$") and "una clave segura" not in stored
    assert verify_password(stored, "una clave segura")
    assert not verify_password(stored, "otra clave")
    assert not verify_password("!", "lo que sea")  # el dueño sin contraseña no entra


def test_la_sesion_firmada_no_se_puede_falsificar_y_vence():
    now = [1_000_000.0]
    auth = AuthService(None, "a" * 40, session_days=1, clock=lambda: now[0])  # type: ignore[arg-type]
    user = type("U", (), {"id": 7, "role": "member"})()
    token = auth.issue(user)
    assert auth.read(token).user_id == 7

    other = AuthService(None, "b" * 40)  # type: ignore[arg-type]
    assert other.read(token) is None  # firmada con otra clave
    assert auth.read(token[:-2] + "xx") is None  # alterada
    now[0] += 86400 + 1
    assert auth.read(token) is None  # vencida


# ---------- Con base de datos ----------


@pytest.fixture
def auth(app_session_factory: async_sessionmaker) -> AuthService:
    return AuthService(app_session_factory, "clave-de-prueba-" * 3)


def make_client(app_session_factory, auth, memory=None) -> httpx.AsyncClient:
    app = create_app()
    app.state.agent_token = AGENT_TOKEN
    settings = Settings(auth_enabled=True)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session_factory] = lambda: app_session_factory
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_llm] = lambda: FakeLLM("Con gusto.")
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    if memory is not None:
        app.dependency_overrides[get_memory_service] = lambda: memory
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def setup_owner(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/auth/setup", json={"password": OWNER_PASSWORD})
    assert response.status_code == 200


@pytest.mark.db
async def test_sin_sesion_todo_lleva_a_entrar(app_session_factory, auth):
    async with make_client(app_session_factory, auth) as client:
        page = await client.get("/memoria")
        assert page.status_code == 303 and page.headers["location"] == "/login?next=/memoria"
        assert (await client.get("/login")).status_code == 200
        assert (await client.get("/api/memories")).status_code == 401
        assert (await client.get("/api/memories")).status_code == 401


@pytest.mark.db
async def test_primera_vez_el_dueno_elige_su_contraseña_una_sola_vez(app_session_factory, auth):
    async with make_client(app_session_factory, auth) as client:
        assert (await client.get("/api/auth/me")).json()["needs_setup"] is True
        await setup_owner(client)
        assert SESSION_COOKIE in client.cookies
        me = (await client.get("/api/auth/me")).json()
        assert me["user"]["role"] == "owner" and me["needs_setup"] is False
        again = await client.post("/api/auth/setup", json={"password": "otra-clave-larga"})
        assert again.status_code == 409


@pytest.mark.db
async def test_entrar_salir_y_limite_de_intentos(app_session_factory, auth):
    async with make_client(app_session_factory, auth) as client:
        await setup_owner(client)
        await client.post("/api/auth/logout")
        client.cookies.clear()
        assert (await client.get("/api/memories")).status_code == 401

        bad = {"username": "dueno", "password": "equivocada"}
        for _ in range(4):
            assert (await client.post("/api/auth/login", json=bad)).status_code == 401
        assert (await client.post("/api/auth/login", json=bad)).status_code == 401  # 5.º
        good = {"username": "dueno", "password": OWNER_PASSWORD}
        locked = await client.post("/api/auth/login", json=good)
        assert locked.status_code == 429  # bloqueado aunque ahora sea la correcta
        assert "Retry-After" in locked.headers

        auth._failures.clear()  # pasaron los 5 minutos
        assert (await client.post("/api/auth/login", json=good)).status_code == 200
        assert (await client.get("/api/memories")).status_code == 200


@pytest.mark.db
async def test_roles_dueno_familia_e_invitado(app_session_factory, auth):
    learned = [Learned(memory_id=1, content="Le gusta el té.", updated=False)]
    memory = FakeMemory(learned=learned)
    async with make_client(app_session_factory, auth, memory) as owner:
        await setup_owner(owner)
        for username, role in (("laura", "member"), ("visita", "guest")):
            created = await owner.post(
                "/api/users",
                json={"username": username, "password": "clave-larga-1", "role": role},
            )
            assert created.status_code == 201
        assert len((await owner.get("/api/users")).json()) == 3
        # El dueño no puede quitarse a sí mismo el rol.
        own_id = (await owner.get("/api/auth/me")).json()["user"]["id"]
        demote = await owner.patch(f"/api/users/{own_id}", json={"role": "guest"})
        assert demote.status_code == 422

    async with make_client(app_session_factory, auth, memory) as member:
        login = {"username": "laura", "password": "clave-larga-1"}
        assert (await member.post("/api/auth/login", json=login)).status_code == 200
        assert (await member.get("/api/memories")).status_code == 200
        assert (await member.get("/api/users")).status_code == 403  # sólo el dueño
        assert (await member.get("/usuarios")).headers["location"] == "/"
        # Lo que el dueño dice por el micrófono del PC no lo ve nadie más.
        assert (await member.get("/api/voice/agent")).status_code == 403
        assert "agent-status.js" not in (await member.get("/")).text
        chat = await member.post("/api/chat", json={"message": "Me gusta el té verde."})
        assert "memory" in [json.loads(line)["type"] for line in chat.text.splitlines()]

    async with make_client(app_session_factory, auth, memory) as guest:
        login = {"username": "visita", "password": "clave-larga-1"}
        assert (await guest.post("/api/auth/login", json=login)).status_code == 200
        assert (await guest.get("/api/memories")).status_code == 403
        assert (await guest.get("/api/knowledge/sources")).status_code == 403
        assert (await guest.get("/memoria")).headers["location"] == "/"
        assert (await guest.get("/conocimiento")).headers["location"] == "/"
        assert (await guest.get("/")).status_code == 200  # el chat sí
        chat = await guest.post("/api/chat", json={"message": "Me gusta el té verde."})
        types = [json.loads(line)["type"] for line in chat.text.splitlines()]
        assert "end" in types and "memory" not in types  # de las visitas no aprende


@pytest.mark.db
async def test_desactivar_a_alguien_lo_saca(app_session_factory, auth):
    async with make_client(app_session_factory, auth) as owner:
        await setup_owner(owner)
        created = await owner.post(
            "/api/users", json={"username": "ana", "password": "clave-larga-1", "role": "member"}
        )
        user_id = created.json()["id"]
        async with make_client(app_session_factory, auth) as ana:
            login = {"username": "ana", "password": "clave-larga-1"}
            assert (await ana.post("/api/auth/login", json=login)).status_code == 200
            await owner.patch(f"/api/users/{user_id}", json={"is_active": False})
            assert (await ana.get("/api/memories")).status_code == 401
            assert (await ana.post("/api/auth/login", json=login)).status_code == 401


@pytest.mark.db
async def test_el_agente_de_voz_entra_con_su_token(app_session_factory, auth):
    async with make_client(app_session_factory, auth) as client:
        headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}
        assert (await client.get("/api/memories", headers=headers)).status_code == 200
        wrong = {"Authorization": "Bearer otro-token"}
        assert (await client.get("/api/memories", headers=wrong)).status_code == 401


@pytest.mark.db
async def test_usuarios_invalidos(app_session_factory, auth):
    async with make_client(app_session_factory, auth) as owner:
        await setup_owner(owner)
        cases = [
            {"username": "dueno", "password": "clave-larga-1"},  # repetido
            {"username": "con espacios", "password": "clave-larga-1"},
            {"username": "corta", "password": "123"},
        ]
        for body in cases:
            assert (await owner.post("/api/users", json=body)).status_code == 422


class CountingFactory:
    """Fábrica de sesiones falsa que cuenta cuántas siguen abiertas."""

    def __init__(self, user) -> None:
        self.user = user
        self.open = 0
        self.opened = 0

    def __call__(self):
        factory = self

        class FakeSession:
            async def __aenter__(self):
                factory.open += 1
                factory.opened += 1
                return self

            async def __aexit__(self, *exc):
                factory.open -= 1

            async def scalar(self, _stmt):
                return factory.user

            async def get(self, _model, _id):
                return factory.user

        return FakeSession()


async def test_los_websocket_no_ocupan_conexiones():
    """El error del 26 oct: cada WebSocket dejaba ocupada una conexión mientras la
    página estaba abierta, y con varias pestañas se acababan (QueuePool limit)."""
    from types import SimpleNamespace

    from app.core.dependencies import get_optional_user

    owner = SimpleNamespace(id=1, role="owner", is_active=True)
    factory = CountingFactory(owner)
    conn = SimpleNamespace(
        headers={"authorization": f"Bearer {AGENT_TOKEN}"},
        cookies={},
        app=SimpleNamespace(state=SimpleNamespace(agent_token=AGENT_TOKEN)),
    )
    for settings in (Settings(auth_enabled=True), Settings(auth_enabled=False)):
        user = await get_optional_user(conn, settings, factory, None)
        assert user is owner
        assert factory.open == 0  # la consulta terminó y la conexión quedó libre
    assert factory.opened == 2


def test_no_acepta_una_clave_de_sesion_corta():
    with pytest.raises(ValueError):
        AuthService(None, "corta")  # type: ignore[arg-type]
