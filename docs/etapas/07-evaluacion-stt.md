# Evaluación de voz a texto (generado por `scripts/evaluate_stt.py`)

15 frases en español (49 s de audio) con la voz sintética de Windows *Sabina (es-MX)* · CPU int8, 4 hilos · `language=es`, VAD activado.

> Esta tabla es **sin** `initial_prompt`. Con la pista que usa JARVIS, `small` baja a **2,9 % de WER (12/15 frases perfectas)** y 3,1 s por frase. Ver la [bitácora](07-voz-a-texto.md#elección-del-modelo).

| Modelo | WER (menos es mejor) | Frases perfectas | Tiempo por frase | RTF | Carga | RAM |
|---|---|---|---|---|---|---|
| `tiny` | 23.5 % | 5/15 | 0.76 s | 0.24 | 1.0 s | 142 MB |
| `base` | 18.7 % | 4/15 | 1.13 s | 0.36 | 17.9 s | 152 MB |
| `small` | 6.7 % | 10/15 | 3.82 s | 1.21 | 50.8 s | 211 MB |

## `tiny`

| Frase | Transcripción | WER |
|---|---|---|
| Hola JARVIS, ¿cómo estás hoy? | Hola, Harbys, ¿cómo está soy? | 60 % |
| ¿Qué tiempo hace en Bogotá? | que tiempo hacé en Bogotá. | ✅ |
| Recuérdame comprar leche mañana a las ocho de la mañana. | Recuerda mi comprarle eche mañana a la sacho de la mañana. | 60 % |
| ¿Quién escribió Cien años de soledad? | ¿Quién escribió 100 años de soledad? | 17 % |
| Apaga las luces de la sala, por favor. | Apaga las luces de la sala, por favor. | ✅ |
| ¿En qué puerto escucha la base de datos de JARVIS? | En qué puerto escucha la base de datos de Harvys. | 10 % |
| Explícame qué es la inteligencia artificial en dos frases. | Explícame que es la inteligencia artificial en dos frases. | ✅ |
| Pon música tranquila para estudiar. | Pon música tranquila para estudiar. | ✅ |
| ¿Cuántos tokens por segundo genera el modelo? | Cuántos togúquens por segundo general modelo? | 43 % |
| Agrega a la lista del mercado arroz, papa y plátano. | Abrega a la lista del mercado a Ros, papá y plátano. | 30 % |
| ¿Cuál es la capital de Australia? | ¿Cuál es la capital de Australia? | ✅ |
| Dame una receta de ajiaco santafereño. | Dame una receta de agía cosa en tu afereño. | 83 % |
| ¿Qué herramienta se usa para el ajuste fino del modelo? | que herramientas se usa para el ajuste fino del modelo. | 10 % |
| Gracias JARVIS, eso es todo por hoy. | Gracias, Harvys, eso es todo por hoy. | 14 % |
| Necesito un resumen del documento que subí ayer. | Necesito un resumen del documento que subía hier. | 25 % |

## `base`

| Frase | Transcripción | WER |
|---|---|---|
| Hola JARVIS, ¿cómo estás hoy? | Hola Harbys, como estás hoy? | 20 % |
| ¿Qué tiempo hace en Bogotá? | que tiempo hace embogote. | 40 % |
| Recuérdame comprar leche mañana a las ocho de la mañana. | Recuerda me comprarle heche mañana al asocho de la mañana. | 70 % |
| ¿Quién escribió Cien años de soledad? | ¿Quién escribió 100 años de soledad? | 17 % |
| Apaga las luces de la sala, por favor. | Apaga las luces de la sala, por favor. | ✅ |
| ¿En qué puerto escucha la base de datos de JARVIS? | en que puerto escucha la base de datos de Harbys. | 10 % |
| Explícame qué es la inteligencia artificial en dos frases. | explícame que es la inteligencia artificial en dos frases. | ✅ |
| Pon música tranquila para estudiar. | Pon música tranquila para estudiar. | ✅ |
| ¿Cuántos tokens por segundo genera el modelo? | Cuantos toquins por segundo genera el modelo. | 14 % |
| Agrega a la lista del mercado arroz, papa y plátano. | Abrega a la lista del mercado arroz, papa y plátano. | 10 % |
| ¿Cuál es la capital de Australia? | ¿Cuál es la capital de Australia? | ✅ |
| Dame una receta de ajiaco santafereño. | Dame una receta de agíaco Santa Feleño. | 50 % |
| ¿Qué herramienta se usa para el ajuste fino del modelo? | que herramientas se usa para el ajuste fino del modelo. | 10 % |
| Gracias JARVIS, eso es todo por hoy. | Gracias Harbys, eso es todo por hoy. | 14 % |
| Necesito un resumen del documento que subí ayer. | Necesito un resumen del documento que subía hier. | 25 % |

## `small`

| Frase | Transcripción | WER |
|---|---|---|
| Hola JARVIS, ¿cómo estás hoy? | Hola Jarvis, ¿cómo estás hoy? | ✅ |
| ¿Qué tiempo hace en Bogotá? | ¿Qué tiempo hace en Bogotá? | ✅ |
| Recuérdame comprar leche mañana a las ocho de la mañana. | Recuérdame comprar leche mañana a las 8 de la mañana. | 10 % |
| ¿Quién escribió Cien años de soledad? | quien escribió 100 años de soledad. | 17 % |
| Apaga las luces de la sala, por favor. | Apaga las luces de la sala, por favor. | ✅ |
| ¿En qué puerto escucha la base de datos de JARVIS? | ¿En qué puerto escucha la base de datos de Harvis? | 10 % |
| Explícame qué es la inteligencia artificial en dos frases. | Explícame que es la inteligencia artificial en dos frases. | ✅ |
| Pon música tranquila para estudiar. | Pon música tranquila para estudiar. | ✅ |
| ¿Cuántos tokens por segundo genera el modelo? | ¿Cuántos tokens por segundo genera el modelo? | ✅ |
| Agrega a la lista del mercado arroz, papa y plátano. | Agrega a la lista del mercado arroz, papa y plátano. | ✅ |
| ¿Cuál es la capital de Australia? | ¿Cuál es la capital de Australia? | ✅ |
| Dame una receta de ajiaco santafereño. | Dame una receta de Ajéaco Santa Fereño. | 50 % |
| ¿Qué herramienta se usa para el ajuste fino del modelo? | ¿Qué herramienta se usa para el ajuste fino del modelo? | ✅ |
| Gracias JARVIS, eso es todo por hoy. | Gracias Harvis, eso es todo por hoy. | 14 % |
| Necesito un resumen del documento que subí ayer. | Necesito un resumen del documento que subí ayer. | ✅ |
