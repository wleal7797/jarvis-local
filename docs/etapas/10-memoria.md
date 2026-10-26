# Bitácora · Etapa 10: Memoria

**Fecha:** 2026‑10‑26 · **Rama:** `etapa/10-memoria` · **Tecnología:** pgvector (tabla `memories`) · Ollama con salida JSON · bge-m3

## Objetivo
Que JARVIS **recuerde lo que usted le cuenta** ("mi hija se llama Sofía", "soy alérgico a los mariscos") también en conversaciones nuevas, y que usted pueda ver, corregir y borrar esos recuerdos. Además, calificar respuestas con 👍 / 👎 y escribir la respuesta correcta para entrenarlo después.

**Terminado cuando:** le cuenta algo por voz, cierra la conversación, abre otra, y lo recuerda. ✅

```
Conversación 1 (voz)  Usted: Jarvis, mi perro se llama Rocky y es un beagle.
                      JARVIS: ¡Qué nombre tan fuerte para un perro! … Lo tendré presente.
                      Memoria: "Su perro se llama Rocky." · "Rocky es un beagle."
Conversación 2 (voz)  Usted: Jarvis, ¿cómo se llama mi perro y de qué raza es?
                      JARVIS: Su perro se llama Rocky y es un beagle.        (3,1 s)
```

## Cómo se usa

- **Cuéntele cosas** por el chat o por voz. Bajo la respuesta aparece *"Lo recordaré: …"*.
- **Panel "Memoria"** (menú lateral o `http://localhost:8000/memoria`): ver lo que recuerda, enseñarle algo a mano, corregir, cambiar la importancia u olvidar.
- **👍 / 👎** bajo cada respuesta. Con 👎 puede escribir la respuesta correcta.
- **La hora:** "¿qué hora es?" ahora tiene respuesta (reloj del PC).

## Qué se construyó

```
app/services/memory_service.py      # aprender, recordar, corregir y olvidar
app/services/training_service.py    # 👍 / 👎 → ejemplos de entrenamiento
app/repositories/memory_repository.py · training_repository.py
app/controllers/training_controller.py   # /api/memories y /api/messages/{id}/feedback
app/services/prompt_builder.py      # recuerdos + fecha al principio; reloj sólo si lo piden
app/views/templates/memory.html + static/js/memory.js    # panel "Memoria"
app/views/static/js/feedback.js     # 👍 / 👎, corrección y nota "Lo recordaré"
scripts/evaluate_memory.py          # evaluación (ver 10-evaluacion-memoria.md)
tests/test_memory.py                # 18 pruebas
```

Las tablas `memories`, `feedback` y `training_examples` ya existían desde la Etapa 2 (modelo relacional): no hizo falta migración.

## Cómo aprende

```mermaid
sequenceDiagram
  autonumber
  actor U as Usuario
  participant C as ChatController
  participant CS as ChatService
  participant MS as MemoryService
  participant LLM as Ollama (jarvis:base)
  participant DB as PostgreSQL

  U->>C: "Mi perro se llama Rocky y es un beagle"
  C->>CS: answer()
  CS->>MS: facts_for_prompt() — recuerdos + fecha
  CS->>LLM: respuesta (recuerdos al principio)
  LLM-->>U: "… Lo tendré presente."
  Note over C,MS: ya respondió; lo demás va en segundo plano
  C->>MS: learn(respuesta)
  MS->>MS: filtro rápido: ¿suena a dato personal?
  MS->>LLM: JSON {"datos": [...]} con los mismos mensajes del principio
  MS->>MS: ¿cada dato sale de la frase? · tercera persona · sin "hoy"
  MS->>DB: guardar (o reemplazar si se parece ≥ 0,88 a uno existente)
  C-->>U: "Lo recordaré: Su perro se llama Rocky."
```

1. **Filtro rápido sin GPU** (`worth_checking`): sólo las frases con primera persona (*me, mi, soy, tengo, vivo…*) o pedidos de recordar. Las preguntas, saludos y órdenes ni siquiera llegan al modelo.
2. **El modelo extrae los datos** en JSON con forma fija (`format` de Ollama): hasta 3 frases cortas en tercera persona, con importancia del 1 al 5 y fechas exactas ("mañana" → "martes 27 de octubre de 2026").
3. **Controles** que no dependen del modelo:
   - El dato debe compartir una palabra con sentido con la frase (`grounded`): evita que copie recuerdos viejos.
   - Se descartan los estados pasajeros (*hoy, ahora, cansado, hambre*) y las frases que sólo dicen la fecha.
   - Se corrige la primera persona: *Soy → Es, Mi → Su*.
4. **Sin duplicados:** si ya hay un recuerdo con similitud ≥ 0,88 (bge-m3), lo **reemplaza**. "Mi color favorito es el verde" → "…ahora es el azul" corrige el anterior (0,93). Datos distintos con la misma forma ("Su perro se llama Toby" / "Su hija se llama Sofía") quedan en 0,6.

## Cómo recuerda (y por qué no lo hace más lento)

| Dónde va | Qué | Por qué |
|---|---|---|
| Al **principio** del mensaje, como un intercambio previo | La fecha de hoy y **todos** los recuerdos (los más importantes primero, hasta ~500 tokens ≈ 35 recuerdos) | Cambia poco (al aprender algo o al cambiar el día). Ollama reutiliza lo que ya leyó si el principio no cambia: no cuesta tiempo en cada pregunta |
| **Junto a los documentos**, cuando los hay | Los 3 recuerdos más parecidos a la pregunta | El modelo de 4B olvida lo que está lejos de la pregunta: sin esto, con documentos decía *"no tengo información"* |
| Al **final**, sólo si preguntan la hora | *"(Según el reloj de este computador, son las 8:46 a. m.)"* | Si va siempre, el modelo lo repite al final de cada respuesta |

**La revisión en segundo plano usa exactamente el mismo principio de mensaje** (fecha + recuerdos + historial) que la siguiente pregunta. Así no le borra a Ollama lo que tiene en caché: hay una prueba que lo verifica (`test_revisar_la_frase_no_estropea_la_cache…`).

**Por voz, más rápido:** si la pregunta es sobre la persona (*"¿cómo se llama mi perro?"*) y hay recuerdos parecidos, no busca en documentos. Pasó de 15,8 s a **3,1 s**. Por escrito sí busca, porque puede haber documentos personales (Etapa 6).

**Lo que se cuenta no se busca:** "Me gusta el café sin azúcar" ya no busca en los documentos (antes citaba *[1]* sin sentido).

## Calificaciones 👍 / 👎

- `PUT /api/messages/{id}/feedback` con `{"rating": 1 | -1, "correction": "…"}`; se puede cambiar de opinión.
- Con una corrección se crea un **ejemplo de entrenamiento** (pregunta original → respuesta corregida) en el dataset `correcciones-personales`, marcado como **personal**: nunca se enviará a Colab ni a Kaggle. Lo usará la Etapa 12 (LoRA).
- El historial muestra la calificación de cada respuesta.

## Personalidad (Modelfile)
- Ahora sabe que recuerda lo que le cuentan y que puede decir la fecha y la hora.
- "Lo que sabe de la persona no se cita".
- Se quitó "no puede poner recordatorios": puede **recordar** pendientes, pero todavía no **avisar** a una hora (eso es la Etapa 13).

## Evaluación
Ver [10-evaluacion-memoria.md](10-evaluacion-memoria.md): **10/10 datos guardados, 10/10 recordados en otra conversación, 0/8 falsos recuerdos** en la ronda final.

## Problemas encontrados

| Problema | Causa | Solución |
|---|---|---|
| Repetía *"(Fecha y hora actuales: …)"* al final de sus respuestas | La línea iba en cada mensaje y el modelo la imitaba | Fecha al principio (fija todo el día); hora sólo si la preguntan |
| "¿Qué hora es?" → *"no puedo verificarla"* | El Modelfile decía que no tenía reloj | Modelfile: la hora del mensaje es exacta, dígala con seguridad |
| Guardaba un resumen de todos los recuerdos al contar uno nuevo | El modelo copiaba la lista de recuerdos | JSON con una lista de datos, la frase al final y el filtro `grounded` |
| `TypeError: 'function' object is not subscriptable` al arrancar | Un método llamado `list` tapaba el `list` de Python en las anotaciones | Se llama `all_for` |
| Los WebSocket de las pruebas fallaban | El chat ahora pide la memoria, que necesita la base de datos | `FakeMemory` en las pruebas |
| Aprender tarda ~3–10 s después de responder | Revisar la frase con el modelo + bge-m3 (en CPU, puede estar dormido) | Va en segundo plano: no demora la respuesta. Si se hace otra pregunta enseguida, espera ~1–3 s a la GPU |

## Límites conocidos
- **Muchos recuerdos:** caben ~35 al principio de cada conversación. Con más, entran los más importantes; habría que elegirlos por parecido con la pregunta (el índice HNSW de `memories` ya está).
- **No olvida por voz:** "olvida que…" todavía no borra; se hace desde el panel.
- **Recuerda pendientes, no avisa:** "recuérdame comprar leche mañana" queda guardado con la fecha, pero JARVIS no lo dirá solo a esa hora (Etapa 13).
- **Un solo usuario:** todo es del usuario por defecto hasta que exista el inicio de sesión (Etapa 11).

## Conceptos aprendidos

| Concepto | Para qué |
|---|---|
| **Memoria de largo plazo** | Datos que sobreviven a la conversación, guardados con su embedding |
| **Salida estructurada (JSON schema)** | Que el modelo responda con una forma fija que el código puede leer |
| **Grounding** | Comprobar que lo que el modelo extrae está de verdad en la frase |
| **Caché de prefijo** | Ollama no vuelve a leer el principio del mensaje si no cambió: por eso el orden importa |
| **Retroalimentación humana** | 👍 / 👎 y correcciones como materia prima para entrenar |

## Siguiente etapa
**Etapa 11:** seguridad y acceso desde la red local (HTTPS, inicio de sesión y entrar desde el celular).
