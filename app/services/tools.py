"""Herramientas de JARVIS (Etapa 13): que haga cosas, no sólo que responda.

Cómo funciona (tool calling de Ollama):
1. Si la frase parece pedir una herramienta ("recuérdame…", "¿cómo está el computador?",
   "busca en mis archivos…"), se le ofrecen al modelo con su descripción y parámetros.
   Si no, JARVIS responde como siempre (más rápido: no hay un paso extra).
2. El modelo decide si usa alguna y con qué datos. JARVIS la ejecuta aquí (en el PC).
3. El resultado vuelve al modelo, que lo dice con sus palabras.

Cada herramienta declara qué roles la pueden usar: un invitado sólo pregunta la hora.
Ninguna sale a internet.
"""

import asyncio
import json
import logging
import re
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.services.prompt_builder import spanish_date
from app.services.reminder_service import ReminderError, ReminderService, describe

logger = logging.getLogger(__name__)

# Frases que piden herramientas. Si ninguna aparece, no se ofrecen (respuesta directa).
_WANTS_TOOLS = re.compile(
    r"recu[eé]rd(?:a|e)me|recordatorio|av[ií]s(?:a|e)me|alarma|despi[eé]rt|"
    r"en \d+ (?:minutos?|horas?)|en (?:un|una|media) (?:minuto|hora)|"
    r"estado del (?:sistema|computador|pc|equipo)|"
    r"c[oó]mo est[aá] (?:el|mi) (?:computador|pc|equipo)|"
    r"\bcpu\b|\bram\b|memoria ram|disco|tarjeta gr[aá]fica|\bgpu\b|temperatura del|"
    r"busca(?:r|me)? en (?:mis|los) (?:archivos|documentos)|en mis (?:archivos|documentos)|"
    r"borra(?:r)? (?:el|un|ese) recordatorio|cancela(?:r)? (?:el|un|ese) recordatorio",
    re.IGNORECASE,
)


def wants_tools(text: str) -> bool:
    return bool(_WANTS_TOOLS.search(text))


@dataclass(frozen=True)
class ToolContext:
    user_id: int
    role: str
    now: datetime


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    roles: tuple[str, ...] = ("owner", "member")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolCallResult:
    name: str
    arguments: dict[str, Any]
    result: str
    ok: bool = True


@dataclass
class ToolBox:
    tools: list[Tool] = field(default_factory=list)

    def for_role(self, role: str) -> list[Tool]:
        return [t for t in self.tools if role in t.roles]

    async def run(self, name: str, arguments: Any, ctx: ToolContext) -> ToolCallResult:
        if isinstance(arguments, str):  # algunos modelos mandan los argumentos como texto
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
        arguments = arguments if isinstance(arguments, dict) else {}
        tool = next((t for t in self.for_role(ctx.role) if t.name == name), None)
        if tool is None:
            return ToolCallResult(
                name, arguments, f"La herramienta {name} no está disponible.", False
            )
        try:
            return ToolCallResult(name, arguments, await tool.handler(ctx, arguments))
        except ReminderError as exc:
            return ToolCallResult(name, arguments, f"No se pudo: {exc}", False)
        except Exception as exc:
            logger.warning("falló la herramienta", extra={"tool": name, "error": str(exc)})
            return ToolCallResult(
                name, arguments, "La herramienta falló. Inténtelo de nuevo.", False
            )


# ---------- Herramientas ----------


def reminder_tools(reminders: ReminderService) -> list[Tool]:
    async def create(ctx: ToolContext, args: dict[str, Any]) -> str:
        minutes = args.get("en_minutos")
        reminder = await reminders.create(
            ctx.user_id,
            str(args.get("texto", "")),
            in_minutes=float(minutes) if minutes not in (None, "") else None,
            hour=str(args["hora"]) if args.get("hora") else None,
            date=str(args["fecha"]) if args.get("fecha") else None,
        )
        return (
            f"Recordatorio guardado: «{reminder.text}», "
            f"{describe(reminder.due_at.astimezone(ctx.now.tzinfo), ctx.now)}. "
            "A esa hora lo diré en voz alta."
        )

    async def listing(ctx: ToolContext, _args: dict[str, Any]) -> str:
        pending = await reminders.pending(ctx.user_id)
        if not pending:
            return "No hay recordatorios pendientes."
        items = [
            f"«{r.text}» {describe(r.due_at.astimezone(ctx.now.tzinfo), ctx.now)}"
            for r in pending[:10]
        ]
        return f"{len(pending)} pendientes: " + "; ".join(items) + "."

    async def cancel(ctx: ToolContext, args: dict[str, Any]) -> str:
        removed = await reminders.cancel(ctx.user_id, str(args.get("cual", "")))
        return f"Borrado: «{removed.text}»." if removed else "No encontré ese recordatorio."

    return [
        Tool(
            "crear_recordatorio",
            "Programa un aviso: a esa hora JARVIS lo dirá en voz alta. Use en_minutos para "
            "'en 10 minutos', u hora (y fecha si no es hoy) para 'a las 9 de la noche'. "
            "No calcule horas: copie lo que dijo la persona.",
            {
                "type": "object",
                "properties": {
                    "texto": {"type": "string", "description": "Qué recordar, en pocas palabras"},
                    "en_minutos": {"type": "number", "description": "Dentro de cuántos minutos"},
                    "hora": {"type": "string", "description": "Hora: 21:00, 9 pm, 7:30 am"},
                    "fecha": {"type": "string", "description": "hoy, mañana o AAAA-MM-DD"},
                },
                "required": ["texto"],
            },
            create,
        ),
        Tool(
            "listar_recordatorios",
            "Los recordatorios pendientes de la persona.",
            {"type": "object", "properties": {}},
            listing,
        ),
        Tool(
            "borrar_recordatorio",
            "Cancela un recordatorio pendiente.",
            {
                "type": "object",
                "properties": {"cual": {"type": "string", "description": "De qué era"}},
                "required": ["cual"],
            },
            cancel,
        ),
    ]


def _gpu_status() -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    out = subprocess.run(
        [exe, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5,
    )  # fmt: skip
    if out.returncode != 0 or not out.stdout.strip():
        return None
    name, util, used, total, temp = [p.strip() for p in out.stdout.splitlines()[0].split(",")]
    return f"tarjeta gráfica {name}: {util} % de uso, {used} de {total} MB de memoria, {temp} °C"


def system_status() -> str:
    import psutil

    cpu = psutil.cpu_percent(interval=0.3)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\" if psutil.WINDOWS else "/")
    parts = [
        f"procesador al {cpu:.0f} %",
        f"memoria RAM: {ram.percent:.0f} % en uso ({ram.available / 2**30:.1f} GB libres "
        f"de {ram.total / 2**30:.1f} GB)",
        f"disco: {disk.free / 2**30:.0f} GB libres de {disk.total / 2**30:.0f} GB",
    ]
    gpu = _gpu_status()
    if gpu:
        parts.append(gpu)
    return "; ".join(parts) + "."


def system_tools() -> list[Tool]:
    async def status(_ctx: ToolContext, _args: dict[str, Any]) -> str:
        return await asyncio.to_thread(system_status)

    async def clock(ctx: ToolContext, _args: dict[str, Any]) -> str:
        return f"Ahora es {spanish_date(ctx.now)}."

    return [
        Tool(
            "estado_del_sistema",
            "Uso del procesador, la memoria RAM, el disco y la tarjeta gráfica de este PC.",
            {"type": "object", "properties": {}},
            status,
        ),
        Tool(
            "fecha_y_hora",
            "La fecha y la hora actuales según el reloj de este PC.",
            {"type": "object", "properties": {}},
            clock,
            roles=("owner", "member", "guest"),
        ),
    ]


SearchFn = Callable[[str, int], Awaitable[Sequence[Any]]]


def file_tools(search: SearchFn) -> list[Tool]:
    async def find(ctx: ToolContext, args: dict[str, Any]) -> str:
        query = str(args.get("consulta", "")).strip()
        if not query:
            return "Falta qué buscar."
        found = await search(query, ctx.user_id)
        if not found:
            return f"No encontré nada sobre «{query}» en sus archivos."
        lines = []
        for chunk in found[:3]:
            snippet = " ".join(chunk.content.split())[:220]
            lines.append(f"[{chunk.title or 'sin título'}] {snippet}")
        return "Encontré: " + " | ".join(lines)

    return [
        Tool(
            "buscar_en_mis_archivos",
            "Busca en los documentos y archivos que la persona subió a JARVIS.",
            {
                "type": "object",
                "properties": {"consulta": {"type": "string", "description": "Qué buscar"}},
                "required": ["consulta"],
            },
            find,
        )
    ]
