# C4 · Nivel 3: Componentes de la API

**Pregunta que responde:** ¿cómo está organizada por dentro la API JARVIS, el contenedor principal?

La API sigue **MVC**, con dos capas de apoyo que mantienen los controladores delgados:

| Capa MVC | Carpeta | Qué contiene |
|---|---|---|
| **Modelo** | `app/models/`, `app/repositories/` | Entidades SQLAlchemy y el acceso a datos |
| **Vista** | `app/views/` (plantillas y estáticos), `app/schemas/` (JSON) | Lo que ve el usuario: HTML o respuestas JSON |
| **Controlador** | `app/controllers/` | Routers de FastAPI: reciben la petición, validan, llaman servicios y devuelven la vista |
| *Servicios* | `app/services/` | Lógica de negocio: RAG, chat, voz, entrenamiento |
| *Núcleo* | `app/core/` | Configuración, conexión a la BD, seguridad y registros |

```mermaid
C4Component
  title Componentes de la API JARVIS

  Container(webapp, "Aplicación web", "Navegador")
  Container(agent, "Agente de voz", "Python")
  ContainerDb(db, "PostgreSQL + pgvector", "Docker")
  Container(ollama, "Ollama", "Servidor de modelos")

  Container_Boundary(api, "API JARVIS · FastAPI") {
    Component(views, "Vistas", "Jinja2 + estáticos", "Páginas HTML y JS")
    Component(c_auth, "AuthController", "Router", "Login y usuarios")
    Component(c_chat, "ChatController", "Router + WebSocket", "Conversaciones en streaming")
    Component(c_voice, "VoiceController", "WebSocket", "Audio de entrada y de salida")
    Component(c_know, "KnowledgeController", "Router", "Fuentes, documentos e ingesta")
    Component(c_train, "TrainingController", "Router", "Memoria, feedback, datasets y modelos")

    Component(s_chat, "ChatService", "Servicio", "Orquesta cada respuesta")
    Component(s_rag, "RetrievalService", "Servicio", "Búsqueda híbrida y RRF")
    Component(s_mem, "MemoryService", "Servicio", "Memoria a largo plazo")
    Component(s_voice, "STT y TTS", "faster-whisper, Piper", "Voz a texto y texto a voz")
    Component(s_ing, "IngestionService", "Servicio", "Registra fuentes y tareas")
    Component(s_train, "TrainingService", "Servicio", "Datasets y versiones de modelo")
    Component(s_llm, "OllamaProvider", "Cliente HTTP", "Chat y embeddings")
    Component(repos, "Repositorios", "SQLAlchemy", "Acceso a datos")
  }

  Rel(webapp, views, "GET páginas", "HTTPS")
  Rel(webapp, c_chat, "Mensajes", "WebSocket")
  Rel(agent, c_voice, "Audio", "WebSocket")
  Rel(c_chat, s_chat, "Usa")
  Rel(c_voice, s_voice, "Usa")
  Rel(c_voice, s_chat, "Usa")
  Rel(c_know, s_ing, "Usa")
  Rel(c_train, s_train, "Usa")
  Rel(c_train, s_mem, "Usa")
  Rel(s_chat, s_rag, "Busca contexto")
  Rel(s_chat, s_mem, "Recuerda")
  Rel(s_chat, s_llm, "Genera")
  Rel(s_rag, s_llm, "Embeddings")
  Rel(s_rag, repos, "Consulta")
  Rel(s_chat, repos, "Guarda")
  Rel(repos, db, "SQL")
  Rel(s_llm, ollama, "HTTP")

  UpdateLayoutConfig($c4ShapeInRow="4", $c4BoundaryInRow="1")
```

## Flujo de una pregunta por voz

```mermaid
sequenceDiagram
  autonumber
  actor U as Usuario
  participant V as Vista (navegador)
  participant VC as VoiceController
  participant STT as FasterWhisperSTT
  participant CS as ChatService
  participant RS as RetrievalService
  participant MS as MemoryService
  participant LLM as OllamaProvider
  participant TTS as PiperTTS
  participant DB as PostgreSQL

  U->>V: Habla
  V->>VC: Audio (WebSocket)
  VC->>STT: transcribe(audio)
  STT-->>VC: "¿Cuándo se fundó Bogotá?"
  VC->>CS: answer(usuario, texto)
  CS->>RS: search(texto, k=6)
  RS->>LLM: embed(texto)
  RS->>DB: vector + texto completo (RRF)
  DB-->>RS: fragmentos
  CS->>MS: recall(usuario, texto)
  MS-->>CS: recuerdos relevantes
  CS->>LLM: chat_stream(prompt con contexto)
  loop por cada frase
    LLM-->>CS: tokens
    CS-->>VC: texto parcial
    VC->>TTS: synthesize(frase)
    TTS-->>V: audio
  end
  CS->>DB: guarda mensaje y fuentes citadas
  V-->>U: Escucha la respuesta
```

## Componentes

| Componente | Responsabilidad | Depende de |
|---|---|---|
| `AuthController` | Login, logout, gestión de usuarios (sólo `owner`) | `AuthService` |
| `ChatController` | Crear y listar conversaciones; WebSocket de chat | `ChatService` |
| `VoiceController` | WebSocket de audio: recibe voz y devuelve texto + audio | `STTService`, `ChatService`, `TTSService` |
| `KnowledgeController` | CRUD de fuentes y documentos; lanzar ingesta | `IngestionService` |
| `TrainingController` | Feedback, memoria, datasets, trabajos de entrenamiento, activar modelos | `TrainingService`, `MemoryService` |
| `ChatService` | Arma el prompt (sistema + memoria + contexto RAG + historial) y guarda el resultado | `RetrievalService`, `MemoryService`, `LLMProvider`, repos |
| `RetrievalService` | Búsqueda vectorial y de texto completo, fusionadas con RRF; filtra los documentos personales por dueño | `EmbeddingService`, `ChunkRepository` |
| `MemoryService` | Extrae y guarda datos sobre el usuario; los recupera por similitud | `EmbeddingService`, `MemoryRepository` |
| `IngestionService` | Registra fuentes, crea tareas; el worker ejecuta `process(job)` | Loaders, `Chunker`, `EmbeddingService` |
| `TrainingService` | Convierte el feedback en ejemplos, exporta JSONL y registra modelos GGUF en Ollama | `ModelManager`, repos |
| `OllamaProvider` | Única puerta hacia Ollama: `chat_stream`, `embed`, `create_model` | Ollama HTTP |
