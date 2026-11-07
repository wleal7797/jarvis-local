r"""Genera training/notebooks/jarvis_voz_piper.ipynb (entrenar una voz propia de Piper en Colab).

    .venv\Scripts\python -m scripts.build_voice_notebook

El cuaderno se escribe desde aquí para poder revisarlo como código (y probar en
tests/test_voice_dataset.py que sus pasos usan el formato que produce Grabar mi voz).
"""

import json
from pathlib import Path

OUT = Path("training/notebooks/jarvis_voz_piper.ipynb")


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text.strip("\n").splitlines(True),
    }


CELLS = [
    md("""
# JARVIS · Entrenar una voz propia (Piper)

Convierte las grabaciones de **Grabar mi voz** (`voz-propia.zip`) en una voz de Piper para JARVIS.
No empieza de cero: parte de una voz española que ya existe y la **ajusta** con sus grabaciones
(*fine-tuning*), así bastan 20–60 minutos de audio.

**Antes de empezar**
1. *Entorno de ejecución › Cambiar tipo de entorno › GPU (T4)*.
2. Tenga a mano `voz-propia.zip` (página *Grabar mi voz › Descargar grabaciones*).
3. El avance se guarda en su Google Drive (`jarvis-voz/`), así puede **seguir entrenando otro día**
   desde donde quedó.

**Privacidad:** sus grabaciones se suben a Google sólo para entrenar. Al terminar, borre
`jarvis-voz/` de su Drive si no piensa seguir. JARVIS no participa: este cuaderno corre en
Colab, no en su PC (el Protocolo Odiseo sigue intacto).

> Sólo use grabaciones de su propia voz, o de alguien que esté de acuerdo.
"""),
    md("## 1. Ajustes"),
    code("""
VOICE_NAME = "jarvis-propia"      # cómo se llamará la voz
BASE = "es_ES/davefx/medium"      # voz de partida: "es_ES/davefx/medium", "es_MX/claude/high"...
ESPEAK = "es-419"                 # pronunciación: "es-419" (Latinoamérica) o "es" (España)
EXTRA_EPOCHS = 1000               # cuánto entrenar en esta sesión (más = mejor, más lento)
BATCH_SIZE = 16                   # bájelo a 8 si aparece "CUDA out of memory"
SAMPLE_EVERY = 250                # cada cuántas épocas hacer muestras para escuchar
TEST_PHRASES = [
    "Buenas noches. Todos los sistemas están en orden.",
    "¿Desea que le recuerde algo para mañana?",
    "Con gusto. Ya apagué las luces de la sala.",
]
"""),
    md("## 2. Preparar Colab (unos 5 minutos)"),
    code("""
!nvidia-smi --query-gpu=name,memory.total --format=csv
from google.colab import drive
drive.mount("/content/drive")
WORK = f"/content/drive/MyDrive/jarvis-voz/{VOICE_NAME}"
!mkdir -p "$WORK"

!git clone -q https://github.com/OHF-Voice/piper1-gpl.git /content/piper1-gpl
%cd /content/piper1-gpl
!pip install -q -e ".[train]"
!./build_monotonic_align.sh
!python setup.py build_ext --inplace
"""),
    md("## 3. Subir las grabaciones"),
    code("""
import csv, wave, zipfile
from pathlib import Path
from google.colab import files

uploaded = files.upload()  # elija voz-propia.zip
zip_name = next(iter(uploaded))
with zipfile.ZipFile(zip_name) as archive:
    archive.extractall("/content")
DATA = Path("/content/voz-propia")

rows = [r for r in csv.reader(open(DATA / "metadata.csv", encoding="utf-8"), delimiter="|")]
seconds, bad = 0.0, []
for name, text in rows:
    with wave.open(str(DATA / "wavs" / name)) as w:
        if (w.getnchannels(), w.getframerate()) != (1, 22050):
            bad.append(name)
        seconds += w.getnframes() / w.getframerate()
print(f"{len(rows)} frases · {seconds / 60:.1f} minutos")
assert not bad, f"Formato distinto a mono 22050 Hz: {bad[:5]}"
if seconds < 15 * 60:
    print("Aviso: con menos de 15 minutos la voz sale poco clara. Sirve para probar.")
"""),
    md("## 4. Voz de partida (o seguir donde quedó)"),
    code("""
import re
from huggingface_hub import hf_hub_download, list_repo_files

def epoch_of(path):
    match = re.search(r"epoch=(\\d+)", str(path))
    return int(match.group(1)) if match else 0

previous = sorted(Path(WORK).rglob("*.ckpt"), key=lambda p: p.stat().st_mtime)
if previous:
    CKPT = str(previous[-1])
    print("Sigo entrenando desde:", CKPT)
else:
    lang = BASE.split("/")[0].split("_")[0]
    prefix = f"{lang}/{BASE}/"
    candidates = [f for f in list_repo_files("rhasspy/piper-checkpoints", repo_type="dataset")
                  if f.startswith(prefix) and f.endswith(".ckpt")]
    assert candidates, f"No encontré un punto de partida para {BASE}"
    CKPT = hf_hub_download("rhasspy/piper-checkpoints", sorted(candidates)[-1], repo_type="dataset")
    print("Parto de:", CKPT)
START_EPOCH = epoch_of(CKPT)
MAX_EPOCHS = START_EPOCH + EXTRA_EPOCHS
print("Épocas:", START_EPOCH, "→", MAX_EPOCHS)
"""),
    md("""
## 5. Entrenar

Tarda horas: déjelo corriendo. Si Colab se desconecta, vuelva a ejecutar los pasos 1 a 4
(el 4 encuentra lo último guardado en Drive) y luego este.
"""),
    code("""
!python -m piper.train fit \\
  --data.voice_name "$VOICE_NAME" \\
  --data.csv_path /content/voz-propia/metadata.csv \\
  --data.audio_dir /content/voz-propia/wavs \\
  --model.sample_rate 22050 \\
  --data.espeak_voice "$ESPEAK" \\
  --data.cache_dir /content/cache \\
  --data.config_path "$WORK/config.json" \\
  --data.batch_size $BATCH_SIZE \\
  --trainer.max_epochs $MAX_EPOCHS \\
  --trainer.default_root_dir "$WORK" \\
  --ckpt_path "$CKPT"
"""),
    md("## 6. Exportar y escuchar cómo va"),
    code("""
import shutil, wave
from IPython.display import Audio, display

last = sorted(Path(WORK).rglob("*.ckpt"), key=lambda p: p.stat().st_mtime)[-1]
OUT = Path("/content/salida"); OUT.mkdir(exist_ok=True)
onnx = OUT / f"{VOICE_NAME}.onnx"
!python -m piper.train.export_onnx --checkpoint "$last" --output-file "$onnx"
shutil.copy(f"{WORK}/config.json", f"{onnx}.json")

from piper import PiperVoice
voice = PiperVoice.load(str(onnx))
for i, text in enumerate(TEST_PHRASES, 1):
    path = OUT / f"muestra-{i}.wav"
    with wave.open(str(path), "wb") as w:
        voice.synthesize_wav(text, w)
    print(text); display(Audio(str(path)))
print("Época:", epoch_of(last))
"""),
    md("""
## 7. Descargar e instalar en JARVIS

Si le gusta, descargue los dos archivos y súbalos en JARVIS: *Voz de JARVIS › Agregar una voz
propia*. Si todavía suena metálica o borrosa: grabe más frases o vuelva al paso 5 con más
`EXTRA_EPOCHS`.
"""),
    code("""
files.download(str(onnx))
files.download(f"{onnx}.json")
"""),
]


def build() -> dict:
    return {
        "cells": CELLS,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("listo:", OUT)


if __name__ == "__main__":
    main()
