# 01 · Requisitos de hardware y memoria

Este documento responde: **¿cuánta memoria necesita el equipo para todo lo que vamos a instalar?**
Distingue tres tipos de memoria, porque cada una se usa para algo distinto:

| Tipo | Qué es | Tu equipo |
|---|---|---|
| **RAM** | Memoria de trabajo del sistema. Todo programa abierto la usa. | 8 GB |
| **VRAM** | Memoria de la tarjeta gráfica. Ahí vive el modelo de lenguaje para responder rápido. | 4 GB (GTX 1650 Ti) |
| **Disco** | Almacenamiento permanente: programas, modelos, datos, base de datos. | 250 GB reservados (302 GB libres) |

Procesador: Intel Core i5‑10300H (4 núcleos / 8 hilos).

---

## 1. RAM y VRAM con JARVIS completo funcionando

Valores aproximados medidos para la configuración elegida (modelo `qwen3:4b-instruct` cuantizado Q4_K_M, contexto de 8 000 tokens).

| Componente | RAM | VRAM | ¿Siempre activo? |
|---|---|---|---|
| Windows 11 + navegador con la app abierta | 3,0 – 3,5 GB | 0,3 GB | Sí |
| Docker Desktop (WSL2) + PostgreSQL + pgvector | 1,0 – 1,5 GB (lo limitamos a 2 GB) | — | Sí |
| Ollama + `qwen3:4b-instruct` (modelo de chat) | 0,5 GB | 3,0 – 3,5 GB | Mientras conversas (se descarga tras 5 min sin uso) |
| Ollama + `bge-m3` (embeddings, en CPU) | 1,2 GB | — | Al buscar o indexar |
| API FastAPI + worker de ingesta | 0,3 – 0,5 GB | — | Sí |
| `faster-whisper small` (voz → texto, CPU int8) | 0,6 GB | — | Al hablar |
| Piper (texto → voz) | 0,1 GB | — | Al responder con voz |
| openWakeWord + Silero VAD ("hey jarvis") | 0,1 GB | — | Si usas palabra de activación |
| Caddy (HTTPS para la red local) | 0,05 GB | — | Sí |
| Reranker `bge-reranker-v2-m3` int8 *(opcional)* | 0,6 GB | — | Al buscar |
| **Total en el peor momento** | **≈ 7,5 – 8,5 GB** | **≈ 3,5 GB** | |

### Conclusión sobre la RAM

- **Mínimo para que funcione: 8 GB (lo que tienes).** Funciona, pero justo. Hay que cerrar programas pesados mientras JARVIS trabaja y dejar que Windows use el archivo de paginación.
- **Recomendado: 16 GB.** Con 16 GB todo corre a la vez sin cuellos de botella y se puede activar el reranker. Es la mejora más barata y la que más se nota.
- **Ideal: 32 GB.** Sólo hace falta si quieres indexar toda la Wikipedia o entrenar en local.

### Conclusión sobre la VRAM

- 4 GB alcanzan para un modelo de **3 000 a 4 000 millones de parámetros** cuantizado (`qwen3:4b`, `gemma3:4b`, `llama3.2:3b`).
- Un modelo de 8B (≈ 5 GB) **no cabe** completo: Ollama pasaría una parte a la CPU y respondería 3 a 5 veces más lento.
- Por eso los embeddings, el reconocimiento de voz y la síntesis de voz corren en la **CPU**, así la GPU queda libre para el modelo de chat.

### Longitud de contexto: 6144 tokens

El *contexto* es la **memoria de corto plazo** de JARVIS: cuánto de la conversación actual (más los documentos del RAG) puede "ver" a la vez. Cada token ocupa espacio en la VRAM (la *caché KV*).

Cálculo para `qwen3:4b` (36 capas, 8 cabezas KV de 128 dimensiones) con la caché comprimida a `q8_0`: **≈ 72 KB por token**.

| Contexto | Caché KV (q8_0) | Pesos del modelo | Total VRAM aprox. | ¿Cabe en 4 GB? |
|---|---|---|---|---|
| 4096 | 0,3 GB | 2,5 GB | ≈ 3,1 GB | ✅ Sobra |
| **6144** | **0,45 GB** | 2,5 GB | **≈ 3,1 GB** | ✅ **Elegido: cabe 100 % en la GPU** |
| 8192 | 0,6 GB | 2,5 GB | ≈ 3,4 GB | ⚠️ Cabe al 88 %: el resto va al procesador |
| 16384 | 1,2 GB | 2,5 GB | ≈ 4,0 GB | ❌ Se sale a la RAM y se vuelve lento |
| 32768 | 2,4 GB | 2,5 GB | ≈ 5,2 GB | ❌ |

6144 tokens equivalen a unas **4 500 palabras**. Se reparten así en cada pregunta:

| Parte del prompt | Tokens |
|---|---|
| Instrucciones de sistema (personalidad JARVIS) | ≈ 700 |
| Fragmentos del RAG (3 × 500) | ≈ 1 800 |
| Historial reciente de la conversación | ≈ 1 600 |
| Espacio para la respuesta y los recuerdos (Etapa 11) | ≈ 2 000 |

> **Historia de esta decisión:** al principio se eligió 8192. En la Etapa 5 se midió que esa GPU lee el contexto a ~250 tokens/s, así que 3 fragmentos bastan, y con 6144 el modelo cabe entero en la GPU: genera más rápido (42,8 contra 33–38 tokens/s), usa 734 MB de RAM y deja libre el procesador.

**La memoria de largo plazo no depende del contexto.** Lo que JARVIS debe recordar para siempre se guarda en PostgreSQL (tabla `memories`, Etapa 11) y se trae al contexto sólo cuando es relevante. Cuando una conversación supera el espacio del historial, los mensajes antiguos se resumen.

Se configura con la variable `OLLAMA_CONTEXT_LENGTH=6144` y en `ollama/Modelfile` (`num_ctx`).

### Rendimiento medido en este equipo (2026‑10‑24)

| Configuración | En GPU | Velocidad | Primera respuesta* |
|---|---|---|---|
| `qwen3:4b` con el margen por defecto (1 GB) | 64 % | 9,5 tokens/s | 214 s (además "piensa" en inglés) |
| `qwen3:4b-instruct`, margen 256 MB, contexto 8192 | 88 % | **40,6 tokens/s** | 6,9 s |
| `qwen3:4b-instruct`, margen 256 MB, contexto 4096 | 100 % | 44,7 tokens/s | 6,0 s |
| **`jarvis:base`, margen 256 MB, contexto 6144** (2026‑10‑25) | **100 %** | **42,8 tokens/s** | 11,1 s de carga, luego inmediato |

\*Incluye cargar el modelo en memoria; las preguntas siguientes son más rápidas.
Edge, Discord y otras apps con aceleración gráfica ocupan ≈ 0,8 GB de VRAM. Cerrarlas libera espacio para el modelo.

### Encender y apagar JARVIS

Cuando no lo uses, por ejemplo para jugar, libera RAM y GPU con un comando:

```powershell
.\scripts\jarvis.ps1 detener              # apaga la API, descarga los modelos y detiene la base (~1,2 GB + toda la GPU)
.\scripts\jarvis.ps1 detener -TodoDocker  # además apaga Docker/WSL (~1 GB más; detiene también otros proyectos)
.\scripts\jarvis.ps1 iniciar              # vuelve a encender todo
.\scripts\jarvis.ps1 estado               # qué está corriendo y cuánta RAM queda
```

Medido el 2026‑10‑25: `detener` liberó **1,24 GB de RAM y los 3,1 GB de la GPU**.

> **Dónde se va la RAM con todo encendido:** Docker Desktop suma ~1,1 GB (ventana 400 MB, servicio 150 MB, máquina virtual 550 MB) para una base que usa 50 MB; el modelo de chat ~0,7 GB; `bge-m3` 1,2 GB mientras está cargado. La app de Claude y el navegador también ocupan 1–2 GB. **La mejora más efectiva sigue siendo pasar a 16 GB de RAM.**

### Cómo ahorramos memoria (decisiones de diseño)

1. **Un solo modelo de chat cargado a la vez** y descarga automática tras 5 min sin uso (`OLLAMA_KEEP_ALIVE=5m`).
2. **Caché de contexto comprimida** en la GPU (`OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_FLASH_ATTENTION=1`) y margen de VRAM reducido (`LLAMA_ARG_FIT_TARGET=256`).
3. **Embeddings en CPU** (`num_gpu: 0` en la petición) para no pelear con el modelo de chat, **con 4 de los 8 hilos** (`OLLAMA_EMBED_THREADS=4`) y descargados a los **2 minutos** (`OLLAMA_EMBED_KEEP_ALIVE=2m`). Con 4 hilos son un 27 % más lentos, pero el procesador no pasa del ~70 % y el PC sigue usable.
4. **WSL2 limitado a 2 GB** y con `autoMemoryReclaim=gradual`, que devuelve a Windows la memoria que Docker no usa (ver [instalación](04-instalacion-paso-a-paso.md)). PostgreSQL configurado para usar poco (`shared_buffers=128MB`, límite de 768 MB; en reposo usa ~20–50 MB).
5. **Sin Redis ni Celery**: la cola de tareas vive en PostgreSQL (`ingestion_jobs` con `FOR UPDATE SKIP LOCKED`).
6. **Vectores en media precisión** (`halfvec`): ocupan la mitad de disco y RAM que `vector`.
7. **Indexación masiva de noche**: el modelo de chat se descarga y los embeddings usan la GPU.

---

## 2. Disco

| Concepto | Espacio |
|---|---|
| Programas: Docker Desktop + WSL2, Python, Ollama, Git, Caddy | ≈ 15 GB |
| Modelos de chat (2 o 3 versiones, incluidas las tuyas entrenadas) | ≈ 10 GB |
| Entorno Python del proyecto (librerías) | ≈ 3 GB |
| Modelos de embeddings, reranker, voz y wake word | ≈ 3 GB |
| Conocimiento descargado en bruto (Wikipedia ES + web + documentación) | 15 – 25 GB |
| Base de datos vectorial (texto + vectores + índices) | 20 – 60 GB |
| Datasets y checkpoints de entrenamiento | ≈ 10 GB |
| Copias de seguridad de la base de datos | ≈ 20 GB |
| Audios y registros | ≈ 5 GB |
| **Total estimado** | **≈ 100 – 150 GB** |

**Caben de sobra en tus 250 GB**, con margen para crecer.

### ¿Cuánto ocupa la Wikipedia vectorizada?

| Alcance | Fragmentos aprox. | Espacio en BD | Tiempo de indexación en tu equipo |
|---|---|---|---|
| Temas seleccionados (≈ 50 000 artículos) | 500 000 | ≈ 3 GB | 1 – 3 horas (GPU) |
| Wikipedia en español completa (≈ 2 M artículos) | 8 M | ≈ 50 GB | 10 – 20 horas (GPU, de noche) |
| Wikipedia en inglés completa | 30 M+ | ≈ 180 GB | Varios días; **no recomendado** con 8 GB de RAM |

Recomendación: empezar con temas seleccionados en la Etapa 6 y crecer cuando la búsqueda funcione bien.

---

## 3. Recomendaciones para un portátil como servidor

- Déjalo **siempre conectado al cargador**.
- En *Configuración → Sistema → Energía*: "Al cerrar la tapa (enchufado) → **No hacer nada**" y suspensión **Nunca** cuando está enchufado.
- Usa una **base con ventilación**. Indexar o entrenar calienta mucho la GPU.
- Conéctalo al router **por cable** si puedes: menos latencia para los demás dispositivos.
