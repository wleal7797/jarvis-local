"""Versiones del modelo de JARVIS (Etapa 12): importar, activar y volver atrás.

Flujo con un modelo ajustado en Colab:

    jarvis-v1.Q4_K_M.gguf  ──import_gguf──►  Modelfile generado  ──ollama create──►  jarvis:v1
                                             (mismo SYSTEM y          │
                                              parámetros que base)    ▼
                                                              model_versions (kind=lora)
    activate("jarvis:v1")  → el chat lo usa desde la siguiente pregunta (sin reiniciar)
    rollback()             → vuelve al que estaba activo antes

El modelo activo vive en la tabla `model_versions` (sólo uno a la vez). Si no hay ninguno,
se usa `OLLAMA_CHAT_MODEL` del .env.
"""

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ModelVersion
from app.repositories import ModelVersionRepository

BASE_MODELFILE = Path("ollama/Modelfile")
GENERATED_DIR = Path("ollama/generados")


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelInfo:
    tag: str
    kind: str
    active: bool
    notes: str | None


_TEMPLATE = re.compile(r'^TEMPLATE """(.*?)"""', re.DOTALL | re.MULTILINE)
_STOP = re.compile(r"^PARAMETER stop .*$", re.MULTILINE)


def chat_format(ollama_modelfile: str) -> str:
    """De la salida de `ollama show --modelfile`: la plantilla de chat en formato Go (el que
    acepta un Modelfile; /api/show la da en Jinja) y las marcas de fin (`stop`)."""
    template = _TEMPLATE.search(ollama_modelfile)
    if not template:
        raise ModelError("El modelo base no tiene plantilla de chat")
    stops = _STOP.findall(ollama_modelfile)
    return f'TEMPLATE """{template.group(1)}"""\n' + "\n".join(stops)


def modelfile_for(gguf: Path, chat: str, base_modelfile: Path = BASE_MODELFILE) -> str:
    """Modelfile del modelo ajustado: el GGUF nuevo con la MISMA personalidad (SYSTEM),
    parámetros y ejemplos que jarvis:base. Sólo cambia de dónde salen los pesos."""
    base = base_modelfile.read_text(encoding="utf-8")
    rest = re.sub(r"^FROM .*$", "", base, count=1, flags=re.MULTILINE).strip()
    return (
        f"# Generado por app/services/model_manager.py a partir de {base_modelfile}\n"
        f"FROM {gguf.resolve().as_posix()}\n\n"
        f"{chat}\n\n"
        f"{rest}\n"
    )


def _run(args: Sequence[str]) -> str:
    result = subprocess.run(
        list(args), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise ModelError((result.stderr or result.stdout).strip())
    return result.stdout


class ModelManager:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        ollama_url: str = "http://127.0.0.1:11434",
        *,
        runner: Callable[[Sequence[str]], str] = _run,
    ) -> None:
        self._session_factory = session_factory
        self._ollama = ollama_url.rstrip("/")
        self._run = runner

    def chat_format_of(self, model: str) -> str:
        """Plantilla de chat del modelo base (Ollama la guarda; el GGUF de Colab no siempre)."""
        return chat_format(self._run(["ollama", "show", "--modelfile", model]))

    async def import_gguf(
        self, gguf: Path, tag: str, *, base_model: str, template_from: str, notes: str = ""
    ) -> ModelVersion:
        if not gguf.exists():
            raise ModelError(f"No existe {gguf}")
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        modelfile = GENERATED_DIR / f"Modelfile.{tag.replace(':', '-')}"
        modelfile.write_text(
            modelfile_for(gguf, self.chat_format_of(template_from)), encoding="utf-8"
        )
        self._run(["ollama", "create", tag, "-f", str(modelfile)])
        async with self._session_factory() as session:
            repo = ModelVersionRepository(session)
            version = await repo.get_by_tag(tag)
            if version is None:
                version = await repo.add(
                    ModelVersion(
                        ollama_tag=tag,
                        base_model=base_model,
                        kind="lora",
                        quantization=_quantization(gguf.name),
                        gguf_path=str(gguf),
                        notes=notes or None,
                    )
                )
            else:
                version.gguf_path = str(gguf)
            await session.commit()
            return version

    async def activate(self, tag: str) -> None:
        async with self._session_factory() as session:
            repo = ModelVersionRepository(session)
            version = await repo.get_by_tag(tag)
            if version is None:
                raise ModelError(f"{tag} no está registrado (importe o ejecute scripts.seed)")
            current = await repo.get_active()
            if current is not None and current.id != version.id:
                # Se recuerda cuál estaba antes, para poder volver.
                version.notes = _with_previous(version.notes, current.ollama_tag)
            await repo.set_active(version)
            await session.commit()

    async def rollback(self) -> str:
        """Vuelve al modelo que estaba activo antes del actual."""
        async with self._session_factory() as session:
            current = await ModelVersionRepository(session).get_active()
        previous = _previous_of(current.notes if current else None)
        if previous is None:
            raise ModelError("No hay un modelo anterior al que volver")
        await self.activate(previous)
        return previous

    async def versions(self) -> list[ModelInfo]:
        async with self._session_factory() as session:
            rows = await session.scalars(select(ModelVersion).order_by(ModelVersion.id))
            return [
                ModelInfo(tag=v.ollama_tag, kind=v.kind, active=v.is_active, notes=v.notes)
                for v in rows.all()
            ]


_PREVIOUS = re.compile(r"\[anterior: ([^\]]+)\]")


def _with_previous(notes: str | None, previous: str) -> str:
    clean = _PREVIOUS.sub("", notes or "").strip()
    return f"{clean} [anterior: {previous}]".strip()


def _previous_of(notes: str | None) -> str | None:
    match = _PREVIOUS.search(notes or "")
    return match.group(1) if match else None


def _quantization(filename: str) -> str | None:
    match = re.search(r"(Q\d_K_[SML]|Q\d_\d|F16|BF16)", filename, re.IGNORECASE)
    return match.group(1).upper() if match else None
