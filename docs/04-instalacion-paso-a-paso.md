# 04 · Instalación paso a paso

Esta guía dice **qué aplicaciones y modelos instalar, en qué orden y en qué etapa**.
Los comandos van en **PowerShell**. Donde dice *(admin)*, abre PowerShell como administrador.

## Estado actual del equipo (revisado el 2026‑10‑24)

| Herramienta | Estado | Acción |
|---|---|---|
| Git 2.45 | ✅ Instalado | — |
| Python 3.13 | ✅ Instalado | Instalar **también** la 3.12 (paso 2) |
| Docker 29.8 + WSL 3.0 | ✅ Instalado | Limitar memoria (paso 5) |
| Ollama 0.40.11 | ✅ Instalado (se actualizó solo al reiniciar) | — |
| GitHub CLI (`gh`) | ❌ Falta | Instalar (paso 3) |
| Driver NVIDIA 572.83 (CUDA 12.8) | ✅ Funciona con Ollama 0.40.11, que trae CUDA 12 | Actualizarlo es opcional |
| Modelos en Ollama | `qwen2.5:3b`, `llama3.2`, `nomic-embed-text` | Descargar `qwen3:4b-instruct` y `bge-m3` (paso 7) |

---

## Ahora (antes de la Etapa 1)

### Paso 1 · Actualizar Ollama
Ollama avisa que hay una versión nueva. Descárgala desde <https://ollama.com/download/windows>, o haz clic derecho en el ícono de Ollama en la bandeja → *Update*.

```powershell
ollama --version   # debe decir 0.40.11 o superior
```

### Paso 2 · Python 3.12 (junto a la 3.13)
Varias librerías de IA (voz, audio, entrenamiento) publican primero sus versiones para Python 3.12. Tener las dos no causa conflictos: el proyecto usará 3.12 dentro de su propio entorno virtual.

```powershell
winget install -e --id Python.Python.3.12
py --list          # debe mostrar -V:3.12 y -V:3.13
```

Si `py` no existe, en la Etapa 1 usaremos la ruta completa: `$env:LOCALAPPDATA\Programs\Python\Python312\python.exe`.

### Paso 3 · GitHub CLI
Sirve para crear el repo y los Pull Requests desde la terminal.

```powershell
winget install -e --id GitHub.cli
# cierra y vuelve a abrir PowerShell
gh auth login      # elige: GitHub.com → HTTPS → Login with a web browser
gh auth status
```

### Paso 4 · Identidad de Git
```powershell
git config --global user.name  "Tu Nombre"
git config --global user.email "tu-correo@ejemplo.com"
git config --global init.defaultBranch main
git config --global core.autocrlf true
```

### Paso 5 · Limitar la memoria de Docker/WSL2
Sin este límite, WSL2 puede tomar hasta la mitad de tu RAM (4 GB).
Crea el archivo `%USERPROFILE%\.wslconfig` con este contenido:

```ini
[wsl2]
memory=2GB
processors=4
swap=4GB

[experimental]
# Devuelve a Windows la memoria que WSL/Docker ya no usa.
autoMemoryReclaim=gradual
sparseVhd=true
```

Luego aplica el cambio:

```powershell
wsl --shutdown
# abre Docker Desktop otra vez
```

### Paso 6 · Configurar Ollama para tu GPU de 4 GB
Estas variables reducen el uso de VRAM y RAM. El porqué de los 6144 tokens de contexto está en [requisitos](01-requisitos-de-hardware.md#longitud-de-contexto-6144-tokens):

```powershell
setx OLLAMA_CONTEXT_LENGTH "6144"
setx OLLAMA_KEEP_ALIVE "5m"
setx OLLAMA_MAX_LOADED_MODELS "2"
setx OLLAMA_NUM_PARALLEL "1"
setx OLLAMA_FLASH_ATTENTION "1"
setx OLLAMA_KV_CACHE_TYPE "q8_0"
setx LLAMA_ARG_FIT_TARGET "256"
```

`LLAMA_ARG_FIT_TARGET` es el margen de VRAM (en MB) que Ollama deja libre. El valor por defecto (1024) es demasiado para una GPU de 4 GB: con 256 entran 36 de las 37 capas del modelo en la GPU.

Cierra Ollama desde la bandeja (clic derecho → *Quit*) y vuelve a abrirlo para que tome los valores.

### Paso 7 · Descargar los modelos

| Modelo | Para qué | Tamaño | Comando |
|---|---|---|---|
| `qwen3:4b-instruct` | Chat principal de JARVIS: muy bueno en español y responde directo, sin "pensar en voz alta" | 2,5 GB | `ollama pull qwen3:4b-instruct` |
| `bge-m3` | Embeddings multilingües para pgvector (1024 dimensiones) | 1,2 GB | `ollama pull bge-m3` |
| `gemma3:4b` *(opcional)* | Para comparar en la Etapa 3 | 3,3 GB | `ollama pull gemma3:4b` |

Comprueba que el modelo de chat corre en la GPU:

```powershell
ollama run qwen3:4b-instruct "Preséntate en una frase como JARVIS"
ollama ps          # la columna PROCESSOR debe decir 100% GPU
```

Los modelos que ya tienes (`qwen2.5:3b`, `llama3.2`) sirven como respaldo. `nomic-embed-text` funciona mejor en inglés, por eso usaremos `bge-m3`. Puedes borrar los que no uses con `ollama rm <nombre>`.

### Paso 8 · Editor (recomendado)
[VS Code](https://code.visualstudio.com/) con estas extensiones:

```powershell
code --install-extension ms-python.python
code --install-extension charliermarsh.ruff
code --install-extension bierner.markdown-mermaid
code --install-extension ms-azuretools.vscode-docker
```

`markdown-mermaid` permite ver los diagramas de esta documentación dentro de VS Code.

### Paso 9 · El portátil como servidor
*Configuración → Sistema → Energía y batería*:
- "Al cerrar la tapa, con el equipo enchufado" → **No hacer nada**.
- "Suspender cuando está enchufado" → **Nunca**.

---

## Durante el proyecto (se instala en cada etapa)

No hace falta instalar esto ahora. Cada etapa lo instala y lo documenta.

| Etapa | Qué se instala | Cómo | Tamaño |
|---|---|---|---|
| 1 | FastAPI, Uvicorn, Pydantic, pytest, ruff | `pip` dentro de `.venv` | ~100 MB |
| 2 | Imagen `pgvector/pgvector:pg17` (puerto **5434**, porque 5432 y 5433 ya estaban ocupados) | `docker compose up -d` | ~450 MB |
| 2 | SQLAlchemy, Alembic, psycopg, `pgvector` (Python) | `pip` | ~50 MB |
| 5 | *(opcional)* reranker `bge-reranker-v2-m3` (ONNX int8) | descarga automática desde Hugging Face | ~600 MB |
| 6 | trafilatura, pypdf, python-docx, python-multipart, psutil | `pip` | ~80 MB |
| 6 | Artículos de Wikipedia elegidos (API pública, sin descargar el volcado completo) | panel *Conocimiento* | ~50 KB por artículo |
| 7 | faster-whisper + `av<14` (+ modelo `small`, con Silero VAD incluido) | `pip` (el modelo se descarga solo la primera vez) | ~600 MB |
| 8 | Piper (`piper-tts`) + voces en español | `pip` + `python -m scripts.download_tts_voices` (Piper y Kokoro, a `data/tts`) | ~400 MB |
| 9 | openWakeWord (`hey_jarvis`), sounddevice | `pip` (el modelo se descarga solo) | ~50 MB |
| 10 | Caddy | `winget search caddy` y luego `winget install` con el id que aparezca, o descarga desde <https://caddyserver.com/download> | ~40 MB |
| 10 | argon2-cffi, PyJWT | `pip` | ~5 MB |
| 12 | Cuenta de Google para Colab o cuenta de Kaggle | web | — |
| 12 | *(sólo si entrenas en local)* PyTorch CUDA + Unsloth | `pip` en un entorno aparte `training/.venv` | ~6 GB |

---

## Verificación rápida (cuando termines los pasos 1 a 7)

```powershell
git --version
py -3.12 --version
gh auth status
docker run --rm hello-world
ollama list        # debe incluir qwen3:4b-instruct y bge-m3
```

Si todo responde sin errores, estás listo para la **Etapa 1**.
