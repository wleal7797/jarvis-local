"""Copias de seguridad automáticas de la base de datos (Etapa 13).

Mientras JARVIS está encendido, revisa cada hora: si la última copia tiene más de 24 h,
hace una nueva con `pg_dump` dentro del contenedor y la guarda en `backups/` (no va a Git).
Conserva las últimas 7. No necesita el Programador de tareas de Windows.

Restaurar una copia (ver docs/04-instalacion-paso-a-paso.md):
    docker cp .\\backups\\<archivo>.dump jarvis_db:/tmp/restore.dump
    docker exec jarvis_db pg_restore -U jarvis -d jarvis --clean --if-exists /tmp/restore.dump
"""

import asyncio
import logging
import subprocess
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

EVERY_HOURS = 24
CHECK_EVERY_SECONDS = 3600

Runner = Callable[[Sequence[str]], None]


def _run(args: Sequence[str]) -> None:
    result = subprocess.run(list(args), capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[:300])


class BackupService:
    def __init__(
        self,
        directory: str | Path = "backups",
        *,
        container: str = "jarvis_db",
        database: str = "jarvis",
        user: str = "jarvis",
        keep: int = 7,
        runner: Runner = _run,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._dir = Path(directory)
        self._container = container
        self._database = database
        self._user = user
        self._keep = keep
        self._run = runner
        self._clock = clock

    def backups(self) -> list[Path]:
        """Las copias, de la más nueva a la más vieja."""
        if not self._dir.exists():
            return []
        return sorted(
            self._dir.glob("jarvis_*.dump"), key=lambda p: p.stat().st_mtime, reverse=True
        )

    def due(self) -> bool:
        latest = self.backups()
        return not latest or self._clock() - latest[0].stat().st_mtime > EVERY_HOURS * 3600

    def backup(self) -> Path:
        """Hace una copia ahora y borra las que sobran."""
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(self._clock()).strftime("%Y%m%d_%H%M%S")
        name = f"jarvis_{stamp}.dump"
        remote = f"/tmp/{name}"
        # Formato personalizado (-Fc): comprimido y restaurable tabla por tabla.
        self._run(["docker", "exec", self._container, "pg_dump", "-U", self._user,
                   "-d", self._database, "-Fc", "-f", remote])  # fmt: skip
        try:
            self._run(["docker", "cp", f"{self._container}:{remote}", str(self._dir / name)])
        finally:
            self._run(["docker", "exec", self._container, "rm", "-f", remote])
        for old in self.backups()[self._keep :]:
            old.unlink(missing_ok=True)
        logger.info("copia de seguridad", extra={"archivo": name})
        return self._dir / name

    async def run_watcher(self, every_seconds: float = CHECK_EVERY_SECONDS) -> None:
        """Tarea en segundo plano (la arranca `main.py`)."""
        await asyncio.sleep(60)  # deja arrancar todo antes de la primera revisión
        while True:
            try:
                if self.due():
                    await asyncio.to_thread(self.backup)
            except Exception as exc:  # sin Docker, por ejemplo: se reintenta en una hora
                logger.warning("no se pudo hacer la copia de seguridad", extra={"error": str(exc)})
            await asyncio.sleep(every_seconds)
