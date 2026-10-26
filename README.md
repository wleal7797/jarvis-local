# JARVIS v1.0 · Asistente personal con IA 100 % local

> Un asistente al estilo JARVIS que conversa por **texto y voz**, responde con **fuentes verificables** y **aprende de sus dueños**.
> Corre por completo en un PC de la casa, sin APIs de terceros y sin enviar datos a la nube.

> 🚧 **Proyecto en construcción.** Se desarrolla por etapas y cada una queda documentada en `docs/`.

**Estado:** 🟡 Etapa 10 terminada: recuerda lo que usted le cuenta, también en conversaciones nuevas (panel "Memoria" y 👍 / 👎)

## Inicio rápido

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env                  # y cambia POSTGRES_PASSWORD
docker compose up -d                    # PostgreSQL + pgvector
.\.venv\Scripts\alembic upgrade head
ollama create jarvis:base -f ollama/Modelfile   # personalidad de JARVIS
.\.venv\Scripts\python -m scripts.seed
.\.venv\Scripts\python -m scripts.index_docs   # conocimiento inicial: la documentación
.\.venv\Scripts\python -m scripts.download_tts_voices   # voces para hablar (~400 MB)
.\.venv\Scripts\python -m app          # http://127.0.0.1:8000  (API en /docs)
.\.venv\Scripts\python -m pytest
```

Requisitos previos: ver la [guía de instalación](docs/04-instalacion-paso-a-paso.md).

Día a día: `.\scripts\jarvis.ps1 iniciar` · `detener` (libera RAM y GPU) · `estado`.

---

<p align="center">
  <img src="docs/img/etapa-04-bienvenida.jpg" alt="Pantalla de bienvenida de JARVIS" width="260">
  &nbsp;
  <img src="docs/img/etapa-04-respuesta.jpg" alt="JARVIS respondiendo en el chat" width="260">
</p>

## Principios

1. **Privacidad primero.** Las conversaciones, los documentos y la voz nunca salen del PC.
2. **Responder con fuentes.** El conocimiento vive en una base vectorial local (RAG). JARVIS cita de dónde sale cada respuesta.
3. **Aprender sin filtrar datos.** Los datos personales se usan sólo en local. El ajuste fino en la nube se hace únicamente con datos públicos.
4. **Funcionar en hardware modesto.** Está diseñado para un portátil con GPU de 4 GB y 8 GB de RAM.
5. **Construirlo entendiendo cada pieza.** Hay una etapa por tecnología, cada una documentada.

## Stack

| Capa | Tecnología |
|---|---|
| Modelo de lenguaje | [Ollama](https://ollama.com) + `qwen3:4b-instruct` |
| Embeddings | `bge-m3` (multilingüe, 1024 dimensiones) |
| Base de datos | PostgreSQL 17 + [pgvector](https://github.com/pgvector/pgvector) (Docker) |
| Backend (MVC) | Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic |
| Vista | Jinja2 · WebSocket · JavaScript y CSS propios (sin CDN) |
| Voz a texto | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) + Silero VAD |
| Texto a voz | [Piper](https://github.com/OHF-Voice/piper1-gpl) |
| Palabra de activación | [openWakeWord](https://github.com/dscripka/openWakeWord) ("hey jarvis") |
| Ajuste fino | [Unsloth](https://github.com/unslothai/unsloth) (QLoRA) → GGUF → Ollama |
| HTTPS en la red local | [Caddy](https://caddyserver.com) |

## Arquitectura

```mermaid
flowchart LR
  U((Usuario)) -->|HTTPS LAN| P[Caddy]
  P --> A[API FastAPI · MVC]
  M((Micrófono del PC)) --> VA[Agente de voz<br/>hey jarvis] -->|WebSocket| A
  A --> O[Ollama<br/>qwen3:4b-instruct · bge-m3]
  A --> D[(PostgreSQL<br/>+ pgvector)]
  W[Worker de ingesta] --> D
  W --> O
```

| Documento | Contenido |
|---|---|
| [C4 · Contexto](docs/arquitectura/01-c4-contexto.md) | Quién usa JARVIS y con qué se relaciona |
| [C4 · Contenedores](docs/arquitectura/02-c4-contenedores.md) | Procesos, puertos y comunicación |
| [C4 · Componentes](docs/arquitectura/03-c4-componentes.md) | Estructura MVC de la API y flujo de una pregunta por voz |
| [Diagrama de clases](docs/arquitectura/04-diagrama-de-clases.md) | Modelo de dominio y capa de aplicación |
| [Modelo relacional](docs/arquitectura/05-modelo-relacional.md) | Diagrama ER y SQL de la base de datos |

## Documentación del proyecto

| # | Documento |
|---|---|
| 01 | [Requisitos de hardware y memoria](docs/01-requisitos-de-hardware.md) |
| 02 | [Acceso desde otros dispositivos de la casa](docs/02-acceso-desde-la-red-local.md) |
| 03 | [Etapas del proyecto y entregables](docs/03-etapas-del-proyecto.md) |
| 04 | [Instalación paso a paso](docs/04-instalacion-paso-a-paso.md) |

## Hoja de ruta

| Etapa | Tecnología | Estado |
|---|---|---|
| 0 | Fundaciones: Git, documentación y arquitectura | ✅ |
| 1 | Backend MVC con FastAPI | ✅ [bitácora](docs/etapas/01-fastapi-mvc.md) |
| 2 | PostgreSQL + pgvector | ✅ [bitácora](docs/etapas/02-postgres-pgvector.md) |
| 3 | Ollama: modelo de lenguaje local | ✅ [bitácora](docs/etapas/03-ollama-chat.md) |
| 4 | Vista web | ✅ [bitácora](docs/etapas/04-vista-web.md) |
| 5 | Embeddings y RAG | ✅ [bitácora](docs/etapas/05-embeddings-rag.md) |
| 6 | Ingesta de conocimiento externo | ✅ [bitácora](docs/etapas/06-ingesta.md) |
| 7 | Voz a texto (faster-whisper) | ✅ [bitácora](docs/etapas/07-voz-a-texto.md) |
| 8 | Texto a voz (Piper) | ✅ [bitácora](docs/etapas/08-texto-a-voz.md) |
| 9 | "Jarvis" siempre atento + conversación fluida | ✅ [bitácora](docs/etapas/09-jarvis-siempre-atento.md) |
| 10 | Memoria: recuerda lo que le cuentas | ✅ [bitácora](docs/etapas/10-memoria.md) |
| 11 | Seguridad y acceso en la red local | 🟡 [bitácora](docs/etapas/11-seguridad-red-local.md) · falta probar desde el celular |
| 12 | Fine-tuning con LoRA | ⚪ |
| 13 | Herramientas y versión 1.0 | ⚪ |

## Estructura del repositorio (objetivo)

```
JARVIS v1.0/
├── app/
│   ├── models/          # M · entidades SQLAlchemy
│   ├── repositories/    # M · acceso a datos
│   ├── views/           # V · plantillas Jinja2 y archivos estáticos
│   ├── schemas/         # V · contratos JSON (Pydantic)
│   ├── controllers/     # C · routers FastAPI
│   ├── services/        # lógica de negocio (chat, RAG, voz, entrenamiento)
│   ├── core/            # configuración, BD, seguridad, logging
│   └── main.py
├── worker/              # worker de ingesta
├── agents/voice/        # agente de palabra de activación
├── training/            # notebooks y scripts de LoRA
├── migrations/          # Alembic
├── tests/
├── docs/                # documentación y bitácoras por etapa
├── data/                # (ignorado por Git) corpus, audios, copias
└── models/              # (ignorado por Git) archivos GGUF
```

## Hardware de referencia

Intel Core i5‑10300H · NVIDIA GTX 1650 Ti 4 GB · 8 GB RAM · 250 GB de disco · Windows 11.
