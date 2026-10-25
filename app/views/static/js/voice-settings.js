/* Ajustes de voz: elegir entre las voces descargadas y la velocidad.
 * Los cambios se aplican al instante en el servidor y se recuerdan (data/preferences.json).
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const dialog = $("voice-settings");
  const select = $("voice-select");
  const speed = $("speed");
  const speedValue = $("speed-value");
  const message = $("voice-message");
  if (!dialog) return;

  const LANG = { es_ES: "España", es_MX: "México", es_AR: "Argentina", es_US: "EE. UU." };
  const SAMPLE = "Hola, soy Jarvis. Así sonaré a partir de ahora. ¿Le parece bien?";

  function show(text, isError) {
    message.textContent = text || "";
    message.classList.toggle("is-error", Boolean(isError));
  }

  function describeSpeed(value) {
    const v = Number(value);
    if (Math.abs(v - 1) < 0.01) return "(normal)";
    return v < 1 ? "(más rápida)" : "(más pausada)";
  }

  async function load() {
    show("");
    try {
      const response = await fetch("/api/voice/settings");
      if (!response.ok) throw new Error(response.status);
      const data = await response.json();
      select.replaceChildren();
      data.installed.forEach((v) => {
        const option = document.createElement("option");
        option.value = v.name;
        option.textContent = v.speaker + " · " + (LANG[v.language] || v.language) + (v.quality ? " · " + v.quality : "");
        option.selected = v.name === data.voice;
        select.appendChild(option);
      });
      speed.value = data.length_scale;
      speedValue.textContent = describeSpeed(data.length_scale);
    } catch (_) {
      show("No se pudieron cargar las voces.", true);
    }
  }

  async function save() {
    const response = await fetch("/api/voice/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice: select.value, length_scale: Number(speed.value) }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || response.statusText);
    return body;
  }

  async function test() {
    show("Preparando la voz…");
    try {
      await save();
      const response = await fetch("/api/voice/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: SAMPLE }),
      });
      if (!response.ok) throw new Error(response.status);
      if (window.JarvisSpeaker) window.JarvisSpeaker.playUrl(URL.createObjectURL(await response.blob()));
      show("Guardada. Ésta es la voz de JARVIS ahora.");
    } catch (err) {
      show("No se pudo probar: " + err.message, true);
    }
  }

  speed.addEventListener("input", () => (speedValue.textContent = describeSpeed(speed.value)));
  select.addEventListener("change", () => save().then(() => show("Voz cambiada.")).catch((e) => show(e.message, true)));
  speed.addEventListener("change", () => save().then(() => show("Velocidad guardada.")).catch((e) => show(e.message, true)));
  $("voice-test").addEventListener("click", test);
  $("open-voice-settings").addEventListener("click", () => {
    load();
    dialog.showModal();
  });
})();
