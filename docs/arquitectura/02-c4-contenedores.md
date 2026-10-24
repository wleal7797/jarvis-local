# C4 · Nivel 2: Contenedores

**Pregunta que responde:** ¿qué programas o procesos forman JARVIS y cómo se comunican?

En C4, un *contenedor* es algo que se ejecuta por separado o guarda datos: una app, un servidor, una base de datos. No confundir con un contenedor de Docker.

```mermaid
C4Container
  title Diagrama de contenedores · JARVIS v1.0

  Person(user, "Usuario", "Dueño, familia o invitado")
  System_Ext(web, "Fuentes públicas", "Sólo en desarrollo")

  System_Boundary(pc, "PC servidor · Windows 11 · red de la casa") {
    Container(webapp, "Aplicación web", "HTML, Jinja2, HTMX, JavaScript", "Chat, voz, conocimiento y entrenamiento. Se ejecuta en el navegador.")
    Container(proxy, "Proxy inverso", "Caddy", "HTTPS local con certificado propio")
    Container(api, "API JARVIS", "Python 3.12, FastAPI", "Controladores MVC, servicios, voz a texto y texto a voz")
    Container(worker, "Worker de ingesta", "Python", "Descarga, divide y vectoriza documentos en segundo plano")
    Container(agent, "Agente de voz", "Python, openWakeWord", "Escucha 'hey jarvis' en el micrófono del PC")
    Container(ollama, "Servidor de modelos", "Ollama", "qwen3:4b en GPU y bge-m3 en CPU")
    ContainerDb(db, "Base de datos", "PostgreSQL 17 + pgvector, Docker", "Usuarios, conversaciones, documentos, vectores y entrenamiento")
    ContainerDb(fs, "Disco", "Sistema de archivos", "Datos en bruto, audios, GGUF, datasets y copias")
  }

  Rel(user, webapp, "Usa", "Navegador")
  Rel(webapp, proxy, "Peticiones y WebSocket", "HTTPS :443")
  Rel(proxy, api, "Reenvía", "HTTP :8000")
  Rel(agent, api, "Envía audio y recibe la respuesta", "WebSocket")
  Rel(api, ollama, "Genera texto y embeddings", "HTTP :11434")
  Rel(api, db, "Lee y escribe", "SQL :5432")
  Rel(api, fs, "Audios y archivos subidos")
  Rel(worker, db, "Toma tareas y guarda fragmentos", "SQL")
  Rel(worker, ollama, "Embeddings por lotes", "HTTP")
  Rel(worker, fs, "Datos en bruto")
  Rel(worker, web, "Descarga", "HTTPS")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Contenedores

| Contenedor | Tecnología | Puerto | Responsabilidad | Etapa |
|---|---|---|---|---|
| Aplicación web | Jinja2 + HTMX + JS | — | Interfaz. Graba el micrófono y reproduce audio. | 4, 7, 8 |
| Proxy inverso | Caddy | 443 | HTTPS en la LAN, necesario para usar el micrófono desde el celular | 10 |
| API JARVIS | FastAPI + Uvicorn | 8000 | Núcleo MVC: controladores, servicios y repositorios | 1 – 13 |
| Worker de ingesta | Python (proceso aparte) | — | Tareas largas sin bloquear el chat | 6 |
| Agente de voz | Python + openWakeWord + sounddevice | — | Modo manos libres en el PC | 9 |
| Servidor de modelos | Ollama | 11434 (sólo `127.0.0.1`) | Inferencia del modelo de chat y embeddings | 3, 5 |
| Base de datos | PostgreSQL 17 + pgvector | 5432 (sólo `127.0.0.1`) | Datos relacionales y vectoriales | 2 |
| Disco | Carpetas `data/` y `models/` | — | Archivos grandes que no van en la BD ni en Git | 2 – 12 |

## Decisiones

- **Ollama y PostgreSQL escuchan sólo en `127.0.0.1`.** Otros dispositivos de la casa no pueden acceder a ellos directamente, sólo a través de la API, que exige inicio de sesión.
- **El worker es un proceso aparte** para que indexar miles de documentos no frene las respuestas.
- **Sin Redis ni broker de mensajes**: la cola es la tabla `ingestion_jobs` (`SELECT … FOR UPDATE SKIP LOCKED`). Ahorra RAM.
- **STT y TTS viven dentro de la API** y no en contenedores aparte: con 8 GB de RAM conviene cargar los modelos una sola vez.
