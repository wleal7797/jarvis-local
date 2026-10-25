/* Hablarle a JARVIS: graba con el micrófono, transcribe en el servidor y envía al chat.
 *
 * - Toca el micrófono para empezar y otra vez para terminar (o espera 30 s).
 * - Esc cancela la grabación.
 * - El navegador sólo permite el micrófono en localhost o con HTTPS: desde el celular
 *   funcionará cuando exista el HTTPS de la Etapa 10.
 */
(function () {
  "use strict";

  const button = document.getElementById("mic");
  const status = document.getElementById("voice-status");
  const MAX_MS = 30000;
  const MIN_MS = 400;

  if (!button) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
    button.hidden = true; // navegador sin soporte de grabación
    return;
  }

  let recorder = null;
  let stream = null;
  let chunks = [];
  let startedAt = 0;
  let cancelled = false;
  let ticker = null;
  let autoStop = null;

  function showStatus(text, isError) {
    status.hidden = !text;
    status.textContent = text || "";
    status.classList.toggle("is-error", Boolean(isError));
  }

  function setRecording(on) {
    button.classList.toggle("is-recording", on);
    button.setAttribute("aria-pressed", String(on));
    button.setAttribute("aria-label", on ? "Terminar y enviar" : "Hablar con JARVIS");
  }

  function tick() {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    const left = Math.ceil((MAX_MS - (Date.now() - startedAt)) / 1000);
    showStatus("Escuchando… 0:" + String(seconds).padStart(2, "0") + " · toca el micrófono para enviar" + (left <= 5 ? " (" + left + " s)" : ""));
  }

  async function start() {
    if (window.JarvisChat && window.JarvisChat.isBusy()) return;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch (_) {
      showStatus(
        window.isSecureContext
          ? "No hay permiso para usar el micrófono. Revísalo en la configuración del navegador."
          : "El micrófono sólo funciona en localhost o con HTTPS (llega en la Etapa 10).",
        true
      );
      return;
    }
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    chunks = [];
    cancelled = false;
    recorder.addEventListener("dataavailable", (e) => {
      if (e.data.size) chunks.push(e.data);
    });
    recorder.addEventListener("stop", onStop);
    recorder.start();
    startedAt = Date.now();
    setRecording(true);
    tick();
    ticker = setInterval(tick, 250);
    autoStop = setTimeout(() => stop(false), MAX_MS);
  }

  function stop(cancel) {
    cancelled = Boolean(cancel);
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  async function onStop() {
    clearInterval(ticker);
    clearTimeout(autoStop);
    stream.getTracks().forEach((track) => track.stop());
    setRecording(false);
    if (cancelled) {
      showStatus("");
      return;
    }
    if (Date.now() - startedAt < MIN_MS) {
      showStatus("Fue muy corto. Toca el micrófono, habla y vuelve a tocarlo.", true);
      return;
    }
    const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
    showStatus("Transcribiendo… (la primera vez carga el modelo de voz)");
    button.disabled = true;
    try {
      const form = new FormData();
      form.append("audio", blob, "voz.webm");
      const response = await fetch("/api/voice/transcribe", { method: "POST", body: form });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || response.statusText);
      if (!body.text) {
        showStatus("No te entendí. Intenta de nuevo, un poco más cerca del micrófono.", true);
        return;
      }
      showStatus("");
      const meta = "Por voz · transcrito en " + String(body.processing_seconds).replace(".", ",") + " s";
      if (!window.JarvisChat.send(body.text, { meta: meta })) {
        // Si no se pudo enviar (por ejemplo, sin conexión), el texto queda en la caja.
        const input = document.getElementById("input");
        input.value = body.text;
        input.dispatchEvent(new Event("input"));
      }
    } catch (err) {
      showStatus("No se pudo transcribir: " + err.message, true);
    } finally {
      button.disabled = false;
    }
  }

  button.addEventListener("click", () => {
    if (recorder && recorder.state === "recording") stop(false);
    else start();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && recorder && recorder.state === "recording") stop(true);
  });
})();
