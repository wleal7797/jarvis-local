# Evaluación del RAG (generado por `scripts/evaluate_rag.py`)

Corpus: documentación del proyecto · Modelo: `jarvis:base` · Embeddings: `bge-m3` · top_k=3 · similitud mínima 0.5 (con palabras clave 0.42) · temperatura 0

## Resumen

| Métrica | Resultado |
|---|---|
| La respuesta está en el 1.er fragmento (hit@1) | 38/50 (76 %) |
| La respuesta está entre los fragmentos (hit@3) | 46/50 (92 %) |
| MRR (posición media inversa) | 0.84 |
| **Respuesta correcta CON RAG** | **42/50 (84 %)** |
| Respuesta correcta SIN RAG | 3/50 (6 %) |
| Respuestas con cita [n] | 50/50 (100 %) |
| Preguntas fuera de tema sin contexto (correcto) | 7/10 (70 %) |
| Similitud del mejor fragmento: preguntas del corpus | mín 0.50 · mediana 0.59 |
| Similitud del mejor fragmento: preguntas fuera de tema | máx 0.74 · mediana 0.45 |
| Tiempo medio de búsqueda | 1.94 s |
| Tiempo medio de respuesta con RAG | 9.3 s |

## Detalle por pregunta

| # | Pregunta | Posición | Similitud | Con RAG | Sin RAG | Cita |
|---|---|---|---|---|---|---|
| 1 | ¿En qué puerto escucha la base de datos PostgreSQL de JARVIS? | 2 | 0.614 | ✅ | ❌ | ✅ |
| 2 | ¿Por qué JARVIS no usa el puerto 5433 para PostgreSQL? | 1 | 0.631 | ✅ | ❌ | ✅ |
| 3 | ¿Cuánta memoria de video (VRAM) tiene la tarjeta gráfica del servidor? | 2 | 0.662 | ✅ | ❌ | ✅ |
| 4 | ¿Qué modelo de chat usa JARVIS? | 1 | 0.664 | ✅ | ❌ | ✅ |
| 5 | ¿Qué modelo se usa para calcular los embeddings? | 2 | 0.522 | ✅ | ❌ | ✅ |
| 6 | ¿Cuántas dimensiones tienen los vectores de embeddings? | 1 | 0.505 | ✅ | ✅ | ✅ |
| 7 | ¿Cuál es la longitud de contexto configurada para el modelo? | 1 | 0.601 | ✅ | ❌ | ✅ |
| 8 | ¿Cuántos tokens por segundo genera JARVIS en la GTX 1650 Ti? | 1 | 0.633 | ❌ | ❌ | ✅ |
| 9 | ¿Qué herramienta convertirá la voz en texto? | 2 | 0.624 | ✅ | ❌ | ✅ |
| 10 | ¿Qué motor de síntesis de voz usará JARVIS para hablar? | 1 | 0.615 | ✅ | ❌ | ✅ |
| 11 | ¿Qué librería detecta la palabra de activación? | 1 | 0.547 | ✅ | ❌ | ✅ |
| 12 | ¿Qué proxy inverso se usa para servir HTTPS en la red local? | 1 | 0.567 | ✅ | ❌ | ✅ |
| 13 | ¿Por qué se necesita HTTPS para usar JARVIS desde el celular? | 1 | 0.635 | ✅ | ❌ | ✅ |
| 14 | ¿Con qué algoritmo se guardan las contraseñas? | 1 | 0.515 | ✅ | ✅ | ✅ |
| 15 | ¿Qué roles de usuario existen en JARVIS? | 1 | 0.622 | ✅ | ❌ | ✅ |
| 16 | ¿Cuántas tablas tiene la base de datos de JARVIS? | — | 0.623 | ❌ | ❌ | ✅ |
| 17 | ¿Qué tipo de índice usa pgvector para la búsqueda vectorial? | 1 | 0.554 | ✅ | ✅ | ✅ |
| 18 | ¿Por qué se usa halfvec en lugar de vector? | 1 | 0.645 | ✅ | ❌ | ✅ |
| 19 | ¿Qué técnica combina la búsqueda vectorial y la búsqueda por palabras? | 1 | 0.55 | ❌ | ❌ | ✅ |
| 20 | ¿Dónde se entrena el adaptador LoRA con datos públicos? | 1 | 0.562 | ✅ | ❌ | ✅ |
| 21 | ¿Con qué herramienta se hace el ajuste fino del modelo? | 1 | 0.56 | ✅ | ❌ | ✅ |
| 22 | ¿Dónde se entrenan los datasets que contienen datos personales? | 2 | 0.536 | ✅ | ❌ | ✅ |
| 23 | ¿Cuánta memoria RAM tiene el equipo servidor? | 1 | 0.661 | ✅ | ❌ | ✅ |
| 24 | ¿Cuánta RAM se recomienda para que JARVIS funcione cómodo? | 1 | 0.804 | ✅ | ❌ | ✅ |
| 25 | ¿Qué procesador tiene el servidor de JARVIS? | — | 0.642 | ❌ | ❌ | ✅ |
| 26 | ¿Cuánto espacio ocuparía en la base la Wikipedia en español completa? | 1 | 0.692 | ✅ | ❌ | ✅ |
| 27 | ¿En cuántas etapas está dividido el proyecto? | 1 | 0.633 | ✅ | ❌ | ✅ |
| 28 | ¿De qué trata la Etapa 9 del proyecto? | 1 | 0.516 | ✅ | ❌ | ✅ |
| 29 | En la comparación de modelos, ¿qué modelo dijo que Belalcázar fundó Bogotá? | 1 | 0.631 | ❌ | ❌ | ✅ |
| 30 | ¿Por qué se descartó llama3.2 como modelo de chat? | — | 0.51 | ❌ | ❌ | ✅ |
| 31 | ¿Por qué la vista web no usa HTMX? | 1 | 0.634 | ✅ | ❌ | ✅ |
| 32 | ¿Cuánto tiempo mantiene Ollama el modelo cargado sin uso? | 1 | 0.561 | ✅ | ❌ | ✅ |
| 33 | ¿Para qué sirve la variable LLAMA_ARG_FIT_TARGET? | 1 | 0.532 | ✅ | ❌ | ✅ |
| 34 | ¿Cuál es el límite de memoria configurado para WSL2 y Docker? | 1 | 0.785 | ✅ | ❌ | ✅ |
| 35 | ¿Qué imagen de Docker se usa para la base de datos? | 1 | 0.592 | ✅ | ❌ | ✅ |
| 36 | ¿Cómo se hace una copia de seguridad de la base de datos? | 1 | 0.544 | ✅ | ❌ | ✅ |
| 37 | ¿En qué formato transmite sus respuestas el endpoint POST /api/chat? | 1 | 0.572 | ✅ | ❌ | ✅ |
| 38 | ¿Cuál es la ruta del WebSocket del chat? | 1 | 0.582 | ✅ | ❌ | ✅ |
| 39 | ¿Cuánto tarda la respuesta completa en la vista web con el modelo ya cargado? | 1 | 0.589 | ✅ | ❌ | ✅ |
| 40 | ¿Por qué tarda unos 12 segundos la primera respuesta del día? | 2 | 0.532 | ✅ | ❌ | ✅ |
| 41 | ¿Qué diccionario de idioma usa la búsqueda por texto completo? | 1 | 0.496 | ❌ | ❌ | ✅ |
| 42 | ¿Qué temperatura usa el Modelfile de JARVIS? | 1 | 0.635 | ✅ | ❌ | ✅ |
| 43 | ¿Qué cláusula SQL usa la cola de ingesta para repartir tareas? | — | 0.52 | ❌ | ❌ | ✅ |
| 44 | ¿Cómo podría accederse a JARVIS desde fuera de casa de forma segura? | 1 | 0.691 | ✅ | ❌ | ✅ |
| 45 | ¿Qué puerto abre la regla del firewall de Windows para JARVIS? | 1 | 0.634 | ✅ | ❌ | ✅ |
| 46 | ¿De cuántos tokens son aproximadamente los fragmentos de texto? | 1 | 0.566 | ✅ | ❌ | ✅ |
| 47 | ¿Cuántos tokens se reservan para el historial de la conversación? | 1 | 0.636 | ✅ | ❌ | ✅ |
| 48 | ¿Qué librería se usará para extraer el texto de páginas web? | 2 | 0.522 | ✅ | ❌ | ✅ |
| 49 | ¿Qué cambio de diseño se hizo en CSS para que los títulos largos no desborden la barra lateral? | 1 | 0.504 | ✅ | ❌ | ✅ |
| 50 | ¿Qué versión de pgvector está instalada? | 3 | 0.598 | ✅ | ❌ | ✅ |

## Preguntas fuera de tema

| Pregunta | Similitud | Fragmentos usados |
|---|---|---|
| Hola JARVIS, ¿cómo estás? | 0.562 | 3 |
| ¿Cuál es la capital de Francia? | 0.438 | 1 |
| Cuéntame un chiste corto. | 0.479 | 0 |
| ¿Cuántos planetas tiene el sistema solar? | 0.388 | 0 |
| Dame una receta de arepas. | 0.493 | 0 |
| ¿Quién escribió Cien años de soledad? | 0.289 | 0 |
| ¿Qué es la fotosíntesis? | 0.739 | 3 |
| Gracias, eso es todo. | 0.471 | 0 |
| ¿Cuál es el río más largo del mundo? | 0.319 | 0 |
| Recomiéndame una película de ciencia ficción. | 0.379 | 0 |

## Respuestas que fallaron con RAG

**8. ¿Cuántos tokens por segundo genera JARVIS en la GTX 1650 Ti?**

> No tengo datos sobre la tasa de generación de tokens para una GPU como la GTX 1650 Ti. Los valores proporcionados en los documentos se refieren a velocidades medias en conversaciones con modelos como `qwen3:4b`, pero no especifican el rendimiento en esa configuración específica [2]. No puedo estimar ese dato con precisión basado en la información disponible.

**16. ¿Cuántas tablas tiene la base de datos de JARVIS?**

> La base de datos de JARVIS tiene tres grupos de tablas, como se detalla en el documento [3]: Conversación, Conocimiento y Entrenamiento. En total, se mencionan 10 tablas específicas: `users`, `conversations`, `messages`, `message_sources`, `feedback`, `memories`, `sources`, `documents`, `chunks`, `ingestion_jobs`.    Por lo tanto, la base de datos tiene **10 tablas**. [3]

**19. ¿Qué técnica combina la búsqueda vectorial y la búsqueda por palabras?**

> La técnica que combina la búsqueda vectorial y la búsqueda por palabras es la búsqueda híbrida, que integra el índice HNSW (para vectores) con la columna `tsv` y el índice GIN (para palabras exactas). [2]

**25. ¿Qué procesador tiene el servidor de JARVIS?**

> No se especifica en los documentos el procesador del servidor de JARVIS. Solo se menciona que el sistema corre en una PC con Windows 11 y que utiliza Ollama para ejecutar modelos, pero no se detalla la configuración del procesador [3].

**29. En la comparación de modelos, ¿qué modelo dijo que Belalcázar fundó Bogotá?**

> Ninguno de los modelos mencionados dice que Belalcázar fundó Bogotá. El documento [1] indica que fue Sebastián de Belalcázar quien fundó Bogotá en 1538, pero no especifica cuál modelo lo dijo. Los datos de comparación solo indican el resultado del análisis, no atribuyen la afirmación a un modelo particular.

**30. ¿Por qué se descartó llama3.2 como modelo de chat?**

> No se menciona explícitamente que se haya descartado `llama3.2` como modelo de chat. Se indica que los modelos `qwen2.5:3b` y `llama3.2` sirven como respaldo, lo que implica que no son el principal, pero no que se hayan descartado por razones técnicas [1]. Por tanto, no hay evidencia en los documentos de que se haya decidido reemplazar a `llama3.2` por otro modelo de chat.

**41. ¿Qué diccionario de idioma usa la búsqueda por texto completo?**

> No se menciona explícitamente qué diccionario de idioma utiliza la búsqueda por texto completo en los documentos proporcionados. No puedo inferirlo con certeza basándome únicamente en la información dada [1] y [2].

**43. ¿Qué cláusula SQL usa la cola de ingesta para repartir tareas?**

> La cola de ingesta utiliza la cláusula `CREATE INDEX ON ingestion_jobs (status, created_at);` para optimizar el acceso a las tareas según su estado y momento de creación [2].

