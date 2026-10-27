"""Datasets de entrenamiento (Etapa 12): guardarlos y exportarlos a JSONL.

Formato de cada línea (el que usan Unsloth, TRL y casi todos los entrenadores):

    {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}

**Regla de privacidad:** un dataset marcado `contains_personal_data` (por ejemplo las
correcciones 👎 del dueño, Etapa 10) **no se exporta para la nube**. Sólo para entrenar en
este PC. La nube (Colab) sólo recibe datos públicos o generados.
"""

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import TrainingDataset, TrainingExample
from app.repositories.training_repository import TrainingRepository

Destination = Literal["nube", "local"]
MODELFILE = Path("ollama/Modelfile")


class PrivacyError(PermissionError):
    """Se intentó sacar del PC un dataset con datos personales."""


@dataclass(frozen=True)
class Example:
    user_prompt: str
    assistant_answer: str
    origin: str = "synthetic"


@dataclass(frozen=True)
class DatasetInfo:
    name: str
    personal: bool
    examples: int


def system_prompt(modelfile: Path = MODELFILE) -> str:
    """El SYSTEM del Modelfile: se entrena con la misma personalidad con la que se usa."""
    text = modelfile.read_text(encoding="utf-8")
    match = re.search(r'^SYSTEM\s+"""(.*?)"""', text, re.DOTALL | re.MULTILINE)
    if not match:
        raise ValueError(f"No se encontró SYSTEM en {modelfile}")
    return match.group(1).strip()


class DatasetService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(
        self, name: str, description: str, *, personal: bool, examples: Iterable[Example]
    ) -> int:
        """Agrega ejemplos (sin repetir la misma pregunta con la misma respuesta)."""
        async with self._session_factory() as session:
            repo = TrainingRepository(session)
            dataset = await repo.dataset(name, description, personal)
            existing = set(
                (
                    await session.execute(
                        select(TrainingExample.user_prompt, TrainingExample.assistant_answer).where(
                            TrainingExample.dataset_id == dataset.id
                        )
                    )
                ).all()
            )
            added = 0
            for example in examples:
                key = (example.user_prompt, example.assistant_answer)
                if key in existing:
                    continue
                existing.add(key)
                session.add(
                    TrainingExample(
                        dataset_id=dataset.id,
                        origin=example.origin,
                        user_prompt=example.user_prompt,
                        assistant_answer=example.assistant_answer,
                    )
                )
                added += 1
            await session.commit()
            return added

    async def prompts_in(self, name: str) -> set[str]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(TrainingExample.user_prompt)
                .join(TrainingDataset)
                .where(TrainingDataset.name == name)
            )
            return set(rows.all())

    async def overview(self) -> list[DatasetInfo]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    TrainingDataset.name,
                    TrainingDataset.contains_personal_data,
                    func.count(TrainingExample.id),
                )
                .outerjoin(TrainingExample)
                .group_by(TrainingDataset.id)
                .order_by(TrainingDataset.name)
            )
            return [DatasetInfo(name=r[0], personal=r[1], examples=r[2]) for r in rows]

    async def export_jsonl(
        self,
        names: Sequence[str],
        path: Path,
        destination: Destination,
        system: str | None = None,
    ) -> int:
        """Escribe los ejemplos de esos datasets en `path`. Devuelve cuántos escribió."""
        system = system if system is not None else system_prompt()
        async with self._session_factory() as session:
            datasets = (
                await session.scalars(
                    select(TrainingDataset).where(TrainingDataset.name.in_(names))
                )
            ).all()
            missing = set(names) - {d.name for d in datasets}
            if missing:
                raise LookupError(f"No existe el dataset: {', '.join(sorted(missing))}")
            personal = [d.name for d in datasets if d.contains_personal_data]
            if destination == "nube" and personal:
                raise PrivacyError(
                    f"{', '.join(personal)} tiene datos personales: sólo se entrena en este PC."
                )
            examples = (
                await session.scalars(
                    select(TrainingExample)
                    .where(TrainingExample.dataset_id.in_([d.id for d in datasets]))
                    .order_by(TrainingExample.id)
                )
            ).all()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as file:
            for example in examples:
                record = {
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": example.user_prompt},
                        {"role": "assistant", "content": example.assistant_answer},
                    ]
                }
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return len(examples)
