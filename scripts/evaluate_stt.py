"""Compara modelos de faster-whisper con las frases de eval/stt_frases.txt.

Requiere los audios de prueba: .\\scripts\\generate_stt_samples.ps1
    .venv\\Scripts\\python -m scripts.evaluate_stt [tiny base small]
Resultado: docs/etapas/07-evaluacion-stt.md

Métricas:
- WER (Word Error Rate): % de palabras mal transcritas (0 % = perfecto).
- Tiempo por frase y RTF (tiempo de proceso / duración del audio; < 1 = más rápido que hablar).
- RAM que ocupa el modelo cargado.
"""

import re
import statistics
import sys
import time
import unicodedata
import wave
from pathlib import Path

import psutil
from faster_whisper import WhisperModel

SENTENCES = Path("eval/stt_frases.txt")
AUDIO_DIR = Path("data/stt")
REPORT = Path("docs/etapas/07-evaluacion-stt.md")


def normalize(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", plain)


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference), normalize(hypothesis)
    dist = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, dist[0] = dist[0], i
        for j, h in enumerate(hyp, 1):
            prev, dist[j] = dist[j], min(dist[j] + 1, dist[j - 1] + 1, prev + (r != h))
    return dist[-1] / max(len(ref), 1)


def duration(path: Path) -> float:
    with wave.open(str(path)) as audio:
        return audio.getnframes() / audio.getframerate()


def evaluate(name: str, sentences: list[str], audios: list[Path]) -> dict:
    process = psutil.Process()
    ram_before = process.memory_info().rss
    started = time.perf_counter()
    model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=4)
    load_s = time.perf_counter() - started
    rows = []
    for sentence, audio in zip(sentences, audios, strict=True):
        t0 = time.perf_counter()
        segments, _ = model.transcribe(
            str(audio),
            language="es",
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        elapsed = time.perf_counter() - t0
        rows.append(
            {
                "reference": sentence,
                "text": text,
                "wer": wer(sentence, text),
                "seconds": elapsed,
                "rtf": elapsed / duration(audio),
            }
        )
        print(f"  [{name}] {elapsed:.2f}s  {text}")
    ram_mb = (process.memory_info().rss - ram_before) / 1024 / 1024
    del model
    return {
        "name": name,
        "load_s": load_s,
        "ram_mb": ram_mb,
        "rows": rows,
        "wer": statistics.mean(r["wer"] for r in rows),
        "exact": sum(1 for r in rows if r["wer"] == 0),
        "seconds": statistics.mean(r["seconds"] for r in rows),
        "rtf": statistics.mean(r["rtf"] for r in rows),
    }


def main() -> None:
    names = sys.argv[1:] or ["tiny", "base", "small"]
    sentences = [s for s in SENTENCES.read_text(encoding="utf-8").splitlines() if s.strip()]
    audios = sorted(AUDIO_DIR.glob("*.wav"))
    if len(audios) != len(sentences):
        sys.exit("Faltan audios: ejecuta .\\scripts\\generate_stt_samples.ps1")
    total_audio = sum(duration(a) for a in audios)
    results = [evaluate(name, sentences, audios) for name in names]

    lines = [
        "# Evaluación de voz a texto (generado por `scripts/evaluate_stt.py`)",
        "",
        f"{len(sentences)} frases en español ({total_audio:.0f} s de audio) con la voz sintética "
        "de Windows *Sabina (es-MX)* · CPU int8, 4 hilos · `language=es`, VAD activado.",
        "",
        "| Modelo | WER (menos es mejor) | Frases perfectas | Tiempo por frase "
        "| RTF | Carga | RAM |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| `{r['name']}` | {r['wer'] * 100:.1f} % | {r['exact']}/{len(sentences)} | "
            f"{r['seconds']:.2f} s | {r['rtf']:.2f} | {r['load_s']:.1f} s | {r['ram_mb']:.0f} MB |"
        )
    for r in results:
        lines += ["", f"## `{r['name']}`", "", "| Frase | Transcripción | WER |", "|---|---|---|"]
        for row in r["rows"]:
            mark = "✅" if row["wer"] == 0 else f"{row['wer'] * 100:.0f} %"
            lines.append(f"| {row['reference']} | {row['text']} | {mark} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Informe: {REPORT}")


if __name__ == "__main__":
    main()
