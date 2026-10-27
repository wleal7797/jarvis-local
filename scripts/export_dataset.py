"""Exporta datasets de entrenamiento a JSONL (Etapa 12).

    .venv\\Scripts\\python -m scripts.export_dataset --listar
    .venv\\Scripts\\python -m scripts.export_dataset estilo-jarvis --destino nube
    .venv\\Scripts\\python -m scripts.export_dataset estilo-jarvis correcciones-personales \\
        --destino local

--destino nube   para subir a Google Colab. Se NIEGA si algún dataset tiene datos
                 personales (por ejemplo las correcciones 👎 del dueño).
--destino local  para entrenar en este PC. Acepta cualquier dataset.

Salida: training/datasets/<nombre>.jsonl (la carpeta no se sube a Git).
"""

import argparse
import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.services.dataset_service import DatasetService, PrivacyError

OUT_DIR = Path("training/datasets")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta datasets de entrenamiento a JSONL")
    parser.add_argument("datasets", nargs="*", help="nombres de los datasets")
    parser.add_argument("--destino", choices=["nube", "local"], default="nube")
    parser.add_argument("--listar", action="store_true", help="ver los datasets disponibles")
    args = parser.parse_args()

    engine = create_engine(get_settings().database_url())
    service = DatasetService(create_session_factory(engine))
    try:
        if args.listar or not args.datasets:
            for info in await service.overview():
                kind = "PERSONAL (sólo local)" if info.personal else "público"
                print(f"  {info.name:<28} {info.examples:>5} ejemplos · {kind}")
            return 0
        name = "+".join(args.datasets)
        path = OUT_DIR / f"{name}-{args.destino}.jsonl"
        try:
            count = await service.export_jsonl(args.datasets, path, args.destino)
        except PrivacyError as exc:
            print(f"No se exportó: {exc}")
            return 2
        except LookupError as exc:
            print(exc)
            return 1
        print(f"{count} ejemplos → {path}")
        if args.destino == "nube":
            print("Súbalo a Colab con training/notebooks/jarvis_lora.ipynb (ver la guía).")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
