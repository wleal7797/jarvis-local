# Evaluación · Memoria (Etapa 10)

**Script:** `python -m scripts.evaluate_memory` (con la API encendida). Borra al final los recuerdos y conversaciones que crea.

**Qué mide:**
1. En una conversación se le cuentan **10 datos personales** y **8 frases que no son datos** (saludo, pregunta, orden, "tengo hambre", "estoy cansado hoy"…).
2. En una conversación **nueva** se le pregunta por cada dato.

| Métrica | Ronda 1 | Ronda 2 | Ronda 3 (final) |
|---|---|---|---|
| Datos guardados | 9/10 | 9/10 | **10/10** |
| Recordados en otra conversación | 7/10 | 7/10 | **10/10** |
| Falsos recuerdos | 1/8 | **0/8** | **0/8** |
| Tiempo medio por pregunta (texto, con documentos) | 6,7 s | 5,8 s | 6,2 s |

## Qué falló y cómo se arregló

| Ronda | Falla | Causa | Arreglo |
|---|---|---|---|
| 1 | "¿Cómo me llamo?" → *"Rocky"* | De "mi perro se llama Rocky" guardó **"Se llama Rocky."** (parece el nombre del dueño) | La instrucción pide decir de quién habla: *"Su perro se llama Rocky."* |
| 1 | No guardó "Mi equipo de fútbol es Millonarios" | La lista de temas no incluía aficiones | Se agregaron *aficiones y equipos* |
| 1 | Guardó *"Está cansado hoy."* | El modelo no siempre respeta "algo pasajero" | Filtro: datos con *hoy / ahora* o estados como *cansado, hambre* se descartan |
| 1–2 | "¿En qué trabajo?" → *"No tengo información"* aunque lo sabía | Con documentos en el mensaje, el modelo (4B) se fija en ellos y olvida los recuerdos que están al principio | Junto a los documentos se repiten los **3 recuerdos más parecidos a la pregunta**, y la instrucción dice que lo que sabe de la persona también vale |
| 2 | No guardó el cumpleaños | El modelo devolvió datos viejos (el filtro los descartó) en lugar del nuevo | La frase va **al final** de la instrucción, lo último que lee el modelo |
| 1 | Guardó *"Soy alérgico…"* en primera persona | El modelo a veces no cambia la persona | Corrección automática: *Soy → Es, Mi → Su, Me gusta → Le gusta…* |
| 1 | Repitió *"Debe comprar leche"* al contarle otra cosa | Copia recuerdos que ya conoce | Cada dato debe compartir alguna palabra con sentido con la frase que se dijo (`grounded`) |

## Ejemplo de la ronda final

```
✅ Mi perro se llama Rocky y es un beagle.  →  Su perro se llama Rocky. | Rocky es un beagle.
✅ Soy alérgico a los mariscos.             →  Es alérgico a los mariscos.
✅ Estoy un poco cansado hoy.               →  (nada)
✅ Pon música tranquila, por favor.         →  (nada)

== Conversación nueva ==
✅ ¿Qué raza es mi perro?      →  Su perro, Rocky, es un beagle.
✅ ¿Cuándo es mi cumpleaños?   →  Su cumpleaños es el 14 de agosto.
✅ ¿En qué trabajo?            →  Usted trabaja como ingeniero de sistemas.
```

## Lo que todavía no está bien

- **Citas de más:** cuando hay documentos en el mensaje, a veces escribe *"[1]"* aunque la respuesta salga de la memoria (no se lee en voz alta).
- **Gramática del modelo de 4B:** *"Le llama Camilo"*, *"Está alérgico"*. Lo corregirá el ajuste fino de la Etapa 12.
- **Respuesta dudosa:** a "¿En qué municipio vivo?" dijo que no lo sabía, aunque mencionó Chía en la misma frase.
- **Prueba pequeña:** 10 datos y 8 frases. Con cientos de recuerdos habrá que elegirlos por parecido (ver la bitácora).
