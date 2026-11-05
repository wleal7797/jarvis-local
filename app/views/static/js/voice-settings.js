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
  const effect = $("voice-effect");
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
        const place = LANG[v.language] || v.language;
        option.textContent = v.speaker + (place ? " · " + place : "") + (v.quality ? " · " + v.quality : "") + (v.custom ? " · propia" : "");
        option.selected = v.name === data.voice;
        select.appendChild(option);
      });
      renderCustom(data.installed.filter((v) => v.custom), data.voice);
      speed.value = data.length_scale;
      if (effect) effect.value = data.effect || "ninguno";
      speedValue.textContent = describeSpeed(data.length_scale);
    } catch (_) {
      show("No se pudieron cargar las voces.", true);
    }
  }

  async function save() {
    const response = await fetch("/api/voice/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        voice: select.value,
        length_scale: Number(speed.value),
        effect: effect ? effect.value : undefined,
      }),
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

  // ---------- Voces propias (sólo el dueño ve esta sección) ----------

  const uploadBox = $("voice-upload");
  const customList = $("custom-voices");

  function renderCustom(voices, active) {
    if (!customList) return;
    customList.replaceChildren();
    voices.forEach((v) => {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = v.name + (v.name === active ? " (en uso)" : "");
      li.appendChild(label);
      if (v.name !== active) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "link-btn link-btn--danger";
        remove.textContent = "Quitar";
        remove.addEventListener("click", async () => {
          if (!confirm("¿Quitar la voz «" + v.name + "»? Se borran sus archivos.")) return;
          const response = await fetch("/api/voice/voices/" + encodeURIComponent(v.name), { method: "DELETE" });
          if (response.ok) { show("Voz quitada."); load(); }
          else show((await response.json()).detail || "No se pudo quitar.", true);
        });
        li.appendChild(remove);
      }
      customList.appendChild(li);
    });
  }

  function upload() {
    const model = $("upload-model").files[0];
    const config = $("upload-config").files[0];
    if (!model || !config) {
      show("Elija los dos archivos: el .onnx y el .onnx.json.", true);
      return;
    }
    const form = new FormData();
    form.append("model", model);
    form.append("config", config);
    form.append("name", $("upload-name").value.trim() || model.name);
    const bar = $("upload-progress");
    const button = $("upload-voice");
    // XMLHttpRequest y no fetch: así se ve el avance de un archivo de ~100 MB.
    const request = new XMLHttpRequest();
    request.open("POST", "/api/voice/voices");
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) bar.value = Math.round((event.loaded / event.total) * 100);
      if (bar.value >= 100) show("Probando la voz…");
    });
    request.addEventListener("load", async () => {
      button.disabled = false;
      bar.hidden = true;
      let body = {};
      try { body = JSON.parse(request.responseText); } catch (_) { /* sin cuerpo */ }
      if (request.status === 201) {
        show("Voz «" + body.name + "» instalada (" + body.size_mb + " MB). Elíjala arriba y pulse Probar.");
        $("upload-model").value = "";
        $("upload-config").value = "";
        $("upload-name").value = "";
        await load();
      } else {
        show(typeof body.detail === "string" ? body.detail : "No se pudo instalar la voz.", true);
      }
    });
    request.addEventListener("error", () => {
      button.disabled = false;
      bar.hidden = true;
      show("Se cortó la subida.", true);
    });
    button.disabled = true;
    bar.hidden = false;
    bar.value = 0;
    show("Subiendo…");
    request.send(form);
  }

  if (uploadBox) $("upload-voice").addEventListener("click", upload);

  speed.addEventListener("input", () => (speedValue.textContent = describeSpeed(speed.value)));
  if (effect) effect.addEventListener("change", () => save().then(() => show("Efecto guardado. Pruébelo.")).catch((e) => show(e.message, true)));
  select.addEventListener("change", () => save().then(() => show("Voz cambiada.")).catch((e) => show(e.message, true)));
  speed.addEventListener("change", () => save().then(() => show("Velocidad guardada.")).catch((e) => show(e.message, true)));
  $("voice-test").addEventListener("click", test);
  $("open-voice-settings").addEventListener("click", () => {
    load();
    dialog.showModal();
  });
})();
