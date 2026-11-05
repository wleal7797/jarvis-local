# Mejoras adicionales a la V1

Cambios hechos después de publicar la [versión 1.0.0](https://github.com/wleal7797/jarvis-local/releases/tag/v1.0.0). Cada uno con su explicación, sus pruebas y cómo usarlo.

---

## 1. Voces propias: subir la voz que usted quiera (2026‑11‑05)

En **Voz de JARVIS › Agregar una voz propia** (menú lateral del chat) el **dueño** puede subir una voz nueva. JARVIS la **prueba antes de instalarla** (la carga y le hace decir una frase); si no funciona, no se instala nada.

### Formato: una voz de Piper son dos archivos

| Archivo | Qué es | Ejemplo |
|---|---|---|
| `<nombre>.onnx` | El modelo: la voz en sí. Entre 1 y 300 MB (las voces de Piper pesan 20–120 MB) | `es_CO-mivoz-medium.onnx` |
| `<nombre>.onnx.json` | Su configuración: idioma, frecuencia de muestreo y fonemas. Debe ser **de ese mismo modelo** | `es_CO-mivoz-medium.onnx.json` |

- Los dos son obligatorios y deben ser de la **misma** voz.
- El `.json` tiene que ser el de Piper (con `audio.sample_rate` y `phoneme_id_map`). Si es de una versión vieja con `phoneme_type` mal escrito, JARVIS lo corrige solo.
- **No se puede subir una grabación** (MP3, WAV, M4A). Una voz se *entrena* a partir de grabaciones: ver abajo.
- El nombre puede ser cualquiera de 3 a 60 caracteres (letras, números, `-` o `_`); se limpia solo: *"Mi Voz (abuela)"* → `mi-voz-abuela`.

### Dónde conseguir voces

1. **Voces listas de Piper** (gratis, en muchos idiomas y acentos): [huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices). En cada carpeta (por ejemplo `es/es_MX/claude/high/`) están los dos archivos. Escuche antes los `samples/`. Para el español, las carpetas `es_ES`, `es_MX`, `es_AR`.
   - También se pueden bajar desde la terminal: `python -m scripts.download_tts_voices --list`.
2. **Una voz entrenada por usted.** Con ~1 a 2 horas de grabaciones limpias de una persona se ajusta una voz de Piper partiendo de una existente (*fine-tuning*). Guía oficial: [Piper · Training](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md). Se puede hacer en Google Colab, igual que el ajuste fino de la Etapa 12. El resultado son justamente los dos archivos `.onnx` y `.onnx.json`.

> **Voces de personas reales:** entrene o suba la voz de alguien sólo con su permiso. JARVIS no incluye copias de voces de actores o personas conocidas.

### Cómo se usa
1. *Voz de JARVIS* › **Agregar una voz propia** › escriba un nombre y elija los dos archivos › **Subir y probar**.
2. Elíjala arriba, en **Voz**, y pulse **Probar**. Se puede combinar con el efecto *Película* o *Película grave* y la velocidad.
3. Para quitarla: **Quitar** junto a su nombre (no se puede quitar la que está en uso; las voces descargadas no se pueden quitar desde aquí).

### Privacidad
Las voces subidas quedan en `data/tts/piper/` de este PC (esa carpeta nunca va a Git) y sólo el dueño puede subir o quitar voces.

### Cómo está hecho
- `app/services/voice_library.py`: valida nombre, tamaño y configuración; copia el modelo por partes (no carga 100 MB en la RAM); lo prueba en una carpeta temporal y sólo si funciona lo mueve a su lugar; marca la voz como `"jarvis_subida": true`.
- `POST /api/voice/voices` (subir) y `DELETE /api/voice/voices/{nombre}` (quitar), sólo el dueño.
- La lista de voces lee idioma y calidad del `.json`, así que una voz con cualquier nombre se ve bien.

### Verificado
- Con Piper de verdad: una voz real subida con otro nombre se instaló y la prueba dijo la frase (~5 s); un `.onnx` dañado se rechazó con *"La voz no funcionó al probarla"* y no quedó ningún archivo.
- 15 pruebas en `tests/test_voice_library.py`: nombres (incluido que no pueda salir de la carpeta de voces), configuración, instalar sólo si funciona, rechazar repetidas, chicas y demasiado grandes, quitar sólo las subidas y no la que está en uso, el endpoint (un familiar no puede subir), y que sólo el dueño ve el apartado.
