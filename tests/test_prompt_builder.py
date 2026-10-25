"""Pruebas del armado del prompt (sin base de datos)."""

from app.models import Message
from app.services.chat_service import make_title
from app.services.prompt_builder import build_messages, trim_history


def msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


def test_agrega_la_pregunta_al_final():
    history = [msg("user", "Hola"), msg("assistant", "Buenas tardes.")]
    messages = build_messages(history, "¿Cómo estás?")
    assert [(m.role, m.content) for m in messages] == [
        ("user", "Hola"),
        ("assistant", "Buenas tardes."),
        ("user", "¿Cómo estás?"),
    ]


def test_recorta_el_historial_mas_antiguo():
    history = [msg("user", "a" * 400), msg("assistant", "b" * 400), msg("user", "c" * 400)]
    # Cada mensaje cuesta ~101 tokens: con 250 sólo caben los dos más recientes.
    kept = trim_history(history, budget=250)
    assert [m.content[0] for m in kept] == ["b", "c"]


def test_titulo_corto_queda_igual_y_largo_se_recorta():
    assert make_title("  Hola   JARVIS ") == "Hola JARVIS"
    long_title = make_title("palabra " * 30)
    assert len(long_title) <= 60
    assert long_title.endswith("…")
