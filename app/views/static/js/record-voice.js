/* Grabar mi voz: muestra una frase, la graba con el micrófono y la guarda para entrenar. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const GOAL_MINUTES = 60;
  let total = 0;
  let index = 1;
  let recorder = null;
  let stream = null;
  let chunks = [];
  let player = null;

  async function api(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      } catch (_) {}
      throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
  }

  function message(text, isError) {
    $("rec-message").textContent = text || "";
    $("rec-message").classList.toggle("is-error", Boolean(isError));
  }

  function showOverview(o) {
    total = o.total;
    $("rec-total").textContent = o.total;
    $("stat-recorded").textContent = o.recorded;
    $("stat-minutes").textContent = o.minutes.toFixed(1);
    $("stat-goal").textContent = Math.min(100, Math.round((o.minutes / GOAL_MINUTES) * 100)) + " %";
    $("rec-export").classList.toggle("is-disabled", o.recorded === 0);
    return o;
  }

  async function refresh() {
    return showOverview(await api("/api/voice/dataset"));
  }

  async function show(i) {
    if (i < 1 || i > total) return;
    index = i;
    const p = await api("/api/voice/dataset/phrases/" + i);
    $("rec-index").textContent = i;
    $("rec-phrase").textContent = p.text;
    $("rec-done").hidden = !p.recorded;
    $("rec-play").disabled = !p.recorded;
    $("rec-delete").disabled = !p.recorded;
    $("rec-prev").disabled = i <= 1;
    $("rec-next").disabled = i >= total;
  }

  // ---------- Grabar ----------

  async function start() {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      message("Este navegador no puede grabar. Use Chrome, Edge o Firefox.", true);
      return;
    }
    try {
      // Sin "mejoras" del navegador: para entrenar se quiere la voz tal cual.
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (_) {
      message(
        window.isSecureContext
          ? "No hay permiso para usar el micrófono. Revíselo en la configuración del navegador."
          : "El micrófono sólo funciona en este PC (localhost) o con HTTPS.",
        true
      );
      return;
    }
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 128000 } : undefined);
    chunks = [];
    recorder.addEventListener("dataavailable", (e) => e.data.size && chunks.push(e.data));
    recorder.addEventListener("stop", save);
    recorder.start();
    $("rec-button").textContent = "■ Detener";
    $("rec-button").classList.add("is-recording");
    $("rec-card").classList.add("is-recording");
    message("Grabando… lea la frase y pulse Detener (o Espacio).");
  }

  function stop() {
    if (recorder && recorder.state === "recording") recorder.stop();
    if (stream) stream.getTracks().forEach((t) => t.stop());
    $("rec-button").textContent = "● Grabar";
    $("rec-button").classList.remove("is-recording");
    $("rec-card").classList.remove("is-recording");
  }

  async function save() {
    const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
    const form = new FormData();
    form.append("audio", blob, "frase.webm");
    message("Guardando…");
    try {
      const clip = await api("/api/voice/dataset/phrases/" + index, { method: "POST", body: form });
      await refresh();
      if (clip.warnings.length) {
        await show(index);
        message("Guardada (" + clip.seconds.toFixed(1) + " s), pero: " + clip.warnings.join(" ") + " Puede repetirla.", true);
      } else {
        message("Guardada (" + clip.seconds.toFixed(1) + " s).");
        await show(Math.min(index + 1, total));
      }
    } catch (err) {
      message(err.message, true);
    }
  }

  function toggle() {
    if (recorder && recorder.state === "recording") stop();
    else start();
  }

  function play() {
    if ($("rec-play").disabled) return;
    if (player) player.pause();
    player = new Audio("/api/voice/dataset/phrases/" + index + "/audio?t=" + Date.now());
    player.play();
  }

  async function remove() {
    await api("/api/voice/dataset/phrases/" + index, { method: "DELETE" });
    await refresh();
    await show(index);
    message("Grabación borrada.");
  }

  // ---------- Eventos ----------

  $("rec-button").addEventListener("click", toggle);
  $("rec-play").addEventListener("click", play);
  $("rec-delete").addEventListener("click", () => remove().catch((e) => message(e.message, true)));
  $("rec-prev").addEventListener("click", () => show(index - 1));
  $("rec-next").addEventListener("click", () => show(index + 1));
  $("rec-pending").addEventListener("click", async () => {
    const o = await refresh();
    if (o.next) show(o.next);
    else message("¡Ya grabó todas las frases!");
  });
  $("rec-export").addEventListener("click", (e) => {
    if ($("rec-export").classList.contains("is-disabled")) {
      e.preventDefault();
      message("Todavía no hay frases grabadas.", true);
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select")) return;
    if (e.code === "Space") {
      e.preventDefault();
      toggle();
    } else if (e.key === "ArrowRight") show(index + 1);
    else if (e.key === "ArrowLeft") show(index - 1);
    else if (e.key.toLowerCase() === "r") play();
  });

  refresh()
    .then((o) => {
      if (!o.total) {
        $("rec-phrase").textContent = "No hay frases para grabar (falta training/voz/frases.txt).";
        $("rec-button").disabled = true;
        return;
      }
      return show(o.next || 1);
    })
    .catch((e) => message(e.message, true));
})();
