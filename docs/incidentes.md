# Registro de incidentes

Errores que aparecieron usando JARVIS de verdad: qué se vio, por qué pasó, cómo se corrigió y cómo se evita que vuelva. Cada uno tiene una prueba automática que fallaba con el código anterior.

---

## INC-01 · Se desconectó de la base de datos (26‑oct‑2026)

| | |
|---|---|
| **Síntoma** | JARVIS dejó de transcribir y de conversar; el agente de voz se quedó esperando y la pantalla mostró "Hablando". |
| **Error** | `sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 5 reached, connection timed out, timeout 30.00` en `logs/api-error.log`. |
| **Evidencia** | En PostgreSQL había conexiones `idle in transaction` con la consulta `SELECT users…`, abiertas desde hacía minutos. |
| **Causa raíz** | Etapa 11: para saber quién es el usuario, cada **WebSocket** (chat y estado del agente) abría una sesión de base de datos (`SessionDep`) que duraba **todo el tiempo que la página estuviera abierta**. Cada pestaña ocupaba 2 de las 10 conexiones; al recargar varias veces se agotaron y todo lo que necesitaba la base falló. |
| **Corrección** | `get_optional_user` usa una sesión **corta** (abre, consulta, cierra). |
| **Protecciones** | `pool_timeout=10` (falla rápido en vez de colgar 30 s) · el agente de voz deja de esperar a los 90 s sin respuesta (`RECV_TIMEOUT`). |
| **Prueba** | `tests/test_auth.py::test_los_websocket_no_ocupan_conexiones`. Verificado en vivo: 12 WebSocket abiertos a la vez → 0 conexiones trabadas, la API sigue respondiendo. |
| **Commit** | `bc2c381` (rama `etapa/11-seguridad-red-local`) |

---

## INC-02 · La pantalla quedó en "Hablando" para siempre (26‑oct‑2026)

| | |
|---|---|
| **Síntoma** | El aviso del agente se quedó en *"Hablando · «Jarvis está pensando.»"* aunque JARVIS ya había terminado de hablar. |
| **Evidencia** | `logs/voz.log`: después de las dos respuestas nunca aparece "En espera". `logs/api.log`: el último aviso del agente fue `hablando`; a los 4 min, su señal de vida **volvió a enviar `hablando`** → el propio agente creía que seguía hablando (no era un problema de la pantalla). En el registro hay decenas de transcripciones de frases del cuarto, una cada pocos segundos. |
| **Causa raíz** | Cuando el parlante termina, el agente debe pasar a "en espera". Para no hacerlo entre frases de una misma respuesta (por ejemplo después de "Un momento, lo consulto"), se ignoraba ese aviso **"mientras estuviera ocupado"**. Pero desde la Etapa 10 el agente también está "ocupado" ~1 s cada vez que **transcribe cualquier frase que oye en el cuarto**. Si el parlante terminaba justo en ese momento (frecuente con conversación alrededor), el aviso se perdía y nada lo volvía a dar. |
| **Corrección** | El aviso sólo se pospone mientras **está llegando una respuesta de verdad** (`_answering`), no mientras transcribe frases ajenas. Al terminar la respuesta, el agente revisa si ya se calló. |
| **Protección** | **Vigilante** (`check_stuck`): si el estado dice "hablando" o "atendiendo" pero no suena nada ni está respondiendo durante más de 3 s, vuelve a "en espera" y lo anota en el registro (`estado trabado corregido`). |
| **Pruebas** | `tests/test_voice_agent.py::test_termina_de_hablar_mientras_transcribe_una_frase_del_cuarto` (reproduce el error: falla con el código anterior, pasa con el nuevo) · `test_el_vigilante_corrige_un_estado_trabado` · `test_el_vigilante_no_interrumpe_una_respuesta_en_curso`. |
| **Verificado** | Reinicio → estado `en_espera`; simulación de voz responde y vuelve a "En espera". |

### Línea de tiempo (hora UTC, de los registros)

| Hora | Qué pasó |
|---|---|
| 00:57:51 | El agente arranca: `en_espera` |
| 00:58:17 | "Jarvis, ¿qué me recomiendas para la cena?" → responde (ajiaco) |
| 00:58:35 | Mientras habla, "Jarvis está pensando." → lo interrumpe y responde |
| 00:58:38 | Último aviso real: `hablando` |
| 00:58:4x | El parlante termina mientras transcribe una frase del cuarto → el aviso de "terminé" se descarta |
| 01:01:51 | Señal de vida del agente: vuelve a mandar `hablando` (confirma que el agente quedó trabado) |
