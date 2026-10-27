"""Pruebas de las herramientas (Etapa 13): recordatorios, avisos, estado del PC y copias."""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelVersion, User
from app.services.backup_service import BackupService
from app.services.chat_service import ChatService
from app.services.reminder_service import (
    NoticeHub,
    ReminderError,
    ReminderService,
    describe,
    due_time,
    parse_hour,
)
from app.services.tools import (
    ToolBox,
    ToolContext,
    reminder_tools,
    system_status,
    system_tools,
    wants_tools,
)
from tests.fakes import FakeLLM

pytestmark = pytest.mark.anyio

BOGOTA = timezone(timedelta(hours=-5))
NOW = datetime(2026, 10, 27, 19, 40, tzinfo=BOGOTA)  # lunes 7:40 p. m.

# ---------- Horas: el modelo no calcula, JARVIS sí ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("21:00", (21, 0)),
        ("9 pm", (21, 0)),
        ("9 p. m.", (21, 0)),
        ("9 de la noche", (21, 0)),
        ("7:30 am", (7, 30)),
        ("12 am", (0, 0)),
        ("3 de la tarde", (15, 0)),
        ("7.15", (7, 15)),
    ],
)
def test_entiende_horas_como_las_dice_la_gente(text: str, expected: tuple[int, int]):
    assert parse_hour(text) == expected


def test_en_10_minutos_es_7_50_no_8_40():
    """El modelo de 4B calculaba 20:40 para 'en 10 minutos' a las 7:40 p. m."""
    assert due_time(NOW, in_minutes=10) == NOW + timedelta(minutes=10)


def test_si_la_hora_ya_paso_es_manana():
    due = due_time(NOW, hour="7 pm")
    assert (due.date(), due.hour) == ((NOW + timedelta(days=1)).date(), 19)
    assert due_time(NOW, hour="9 de la noche").date() == NOW.date()
    assert due_time(NOW, hour="7:00 am", date="mañana").day == 28
    assert describe(due_time(NOW, hour="21:00"), NOW) == "hoy a las 9:00 p. m."
    assert describe(due_time(NOW, hour="7 am", date="mañana"), NOW) == "mañana a las 7:00 a. m."


@pytest.mark.parametrize(
    "kwargs",
    [
        {},  # sin hora
        {"in_minutes": -5},
        {"hour": "25:00"},
        {"hour": "a la hora del té"},
        {"hour": "9 am", "date": "2026-10-01"},  # ya pasó
        {"hour": "9 am", "date": "2028-01-01"},  # más de un año
    ],
)
def test_horas_imposibles_dan_un_error_claro(kwargs):
    with pytest.raises(ReminderError):
        due_time(NOW, **kwargs)


# ---------- ¿Cuándo ofrecer herramientas? ----------


@pytest.mark.parametrize(
    ("text", "tools"),
    [
        ("Recuérdame sacar la basura a las 9", True),
        ("Avísame en 10 minutos que apague la estufa", True),
        ("¿Cómo está el computador?", True),
        ("¿Cuánta memoria RAM queda?", True),
        ("Busca en mis archivos el contrato de arriendo", True),
        ("Cancela el recordatorio de la basura", True),
        ("¿Cuál es la capital de Canadá?", False),
        ("Hola Jarvis, ¿cómo estás?", False),
        ("Me gusta el café sin azúcar", False),
    ],
)
def test_solo_ofrece_herramientas_cuando_hacen_falta(text: str, tools: bool):
    assert wants_tools(text) is tools


# ---------- Avisos aislados por usuario ----------


async def test_cada_uno_recibe_sus_avisos_y_los_que_llegaron_sin_nadie_conectado():
    hub = NoticeHub()
    ana, luis = hub.subscribe(1), hub.subscribe(2)
    assert hub.publish(1, {"text": "pastilla"}) == 1
    assert ana.get_nowait()["text"] == "pastilla"
    assert luis.empty()  # el de Ana no le llega a Luis

    assert hub.publish(3, {"text": "llamar al médico"}) == 0  # nadie conectado
    later = hub.subscribe(3)
    assert later.get_nowait()["text"] == "llamar al médico"


# ---------- Con base de datos ----------


@pytest.fixture
async def user(session: AsyncSession) -> User:
    owner = User(username="dueno", display_name="Dueño", password_hash="!", role="owner")
    session.add_all([owner, ModelVersion(ollama_tag="jarvis:base", base_model="Q", kind="base")])
    await session.commit()
    return owner


@pytest.mark.db
async def test_recordatorios_crear_listar_cancelar_y_avisar(session_factory, user: User):
    clock = [NOW]
    service = ReminderService(session_factory, clock=lambda: clock[0])
    await service.create(user.id, "sacar la basura", hour="9 pm")
    await service.create(user.id, "apagar la estufa", in_minutes=10)
    assert [r.text for r in await service.pending(user.id)] == [
        "apagar la estufa",
        "sacar la basura",
    ]

    removed = await service.cancel(user.id, "el de la basura")
    assert removed is not None and removed.text == "sacar la basura"

    assert await service.take_due() == []  # todavía no
    clock[0] = NOW + timedelta(minutes=11)
    due = await service.take_due()
    assert [r.text for r in due] == ["apagar la estufa"] and not due[0].late
    assert service.notice(due[0])["say"] == "Señor, le recuerdo: apagar la estufa."
    assert await service.take_due() == []  # cada uno avisa una sola vez


@pytest.mark.db
async def test_si_estaba_apagado_avisa_tarde(session_factory, user: User):
    clock = [NOW]
    service = ReminderService(session_factory, clock=lambda: clock[0])
    await service.create(user.id, "regar las plantas", hour="8 pm")
    clock[0] = NOW + timedelta(hours=3)  # JARVIS se encendió tres horas después
    (late,) = await service.take_due()
    assert late.late
    assert service.notice(late)["say"].startswith(
        "Señor, tenía pendiente un recordatorio de las 8:00"
    )


@pytest.mark.db
async def test_un_invitado_no_puede_crear_recordatorios(session_factory, user: User):
    box = ToolBox(
        reminder_tools(ReminderService(session_factory, clock=lambda: NOW)) + system_tools()
    )
    guest = ToolContext(user_id=user.id, role="guest", now=NOW)
    assert [t.name for t in box.for_role("guest")] == ["fecha_y_hora"]
    result = await box.run("crear_recordatorio", {"texto": "x", "en_minutos": 5}, guest)
    assert not result.ok and "no está disponible" in result.result

    owner = ToolContext(user_id=user.id, role="owner", now=NOW)
    as_text = await box.run("crear_recordatorio", '{"texto": "x", "en_minutos": 5}', owner)
    assert as_text.ok  # argumentos como texto JSON también sirven
    bad = await box.run("crear_recordatorio", {"texto": "y", "hora": "mañana temprano"}, owner)
    assert not bad.ok and bad.result.startswith("No se pudo")


@pytest.mark.db
async def test_el_chat_usa_la_herramienta_y_lo_dice_con_sus_palabras(session_factory, user: User):
    llm = FakeLLM(
        "Listo, le aviso en 10 minutos.",
        tool_calls=[
            {"function": {"name": "crear_recordatorio",
                          "arguments": {"texto": "apagar la estufa", "en_minutos": 10}}}
        ],
    )  # fmt: skip
    reminders = ReminderService(session_factory, clock=lambda: NOW)
    service = ChatService(
        session_factory, llm, "jarvis:base", tools=ToolBox(reminder_tools(reminders)),
        clock=lambda: NOW,
    )  # fmt: skip
    events = [
        e async for e in service.answer(user.id, "Avísame en 10 minutos que apague la estufa")
    ]

    assert [e for e in events if e["type"] == "tool"] == [
        {"type": "tool", "name": "crear_recordatorio", "ok": True}
    ]
    assert events[-1]["tools"] == ["crear_recordatorio"]
    final_prompt = llm.calls[-1]
    assert final_prompt[-1].role == "tool" and "apagar la estufa" in final_prompt[-1].content
    assert final_prompt[-2].tool_calls  # el pedido del modelo va en el historial
    (pending,) = await reminders.pending(user.id)
    assert pending.due_at == NOW + timedelta(minutes=10)


@pytest.mark.db
async def test_sin_pedido_de_herramienta_no_se_ofrecen(session_factory, user: User):
    llm = FakeLLM("Ottawa.")
    service = ChatService(
        session_factory, llm, "jarvis:base",
        tools=ToolBox(reminder_tools(ReminderService(session_factory))),
    )  # fmt: skip
    events = [e async for e in service.answer(user.id, "¿Cuál es la capital de Canadá?")]
    assert llm.offered_tools == [] and events[-1]["tools"] == []


# ---------- Estado del PC y copias de seguridad ----------


def test_estado_del_sistema_dice_procesador_memoria_y_disco():
    report = system_status()
    assert "procesador" in report and "memoria RAM" in report and "disco" in report


def test_copias_de_seguridad_cada_dia_y_guarda_las_ultimas(tmp_path):
    commands: list[list[str]] = []
    now = [datetime(2026, 10, 27, tzinfo=UTC).timestamp()]

    def runner(args):
        commands.append(list(args))
        if args[1] == "cp":  # "docker cp" crea el archivo
            (tmp_path / args[3].split("\\")[-1].split("/")[-1]).write_bytes(b"PGDMP")

    service = BackupService(tmp_path, keep=2, runner=runner, clock=lambda: now[0])
    assert service.due()  # no hay ninguna
    for _ in range(3):
        service.backup()
        now[0] += 25 * 3600
    assert len(service.backups()) == 2  # sólo las últimas 2
    assert commands[0][:3] == ["docker", "exec", "jarvis_db"] and "-Fc" in commands[0]
    assert commands[-1][-1].startswith("/tmp/")  # limpia el archivo dentro del contenedor
    json.dumps(commands)  # nada raro en los comandos
