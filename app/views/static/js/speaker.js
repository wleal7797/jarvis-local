/* La voz de JARVIS en el navegador: reproduce en orden las frases que llegan del servidor.
 *
 * - `enqueue(base64Wav)`: agrega una frase a la cola (suena en cuanto termina la anterior).
 * - `stop()`: se calla de inmediato y vacía la cola (al enviar otro mensaje o tocar "Detener").
 * - El botón de altavoz activa o desactiva las respuestas en voz alta (se recuerda).
 */
(function () {
  "use strict";

  const toggle = document.getElementById("toggle-voice");
  const stopButton = document.getElementById("stop-voice");
  const KEY = "jarvis-voice";
  const queue = [];
  let current = null;
  let enabled = true;

  try {
    enabled = localStorage.getItem(KEY) !== "off";
  } catch (_) {}

  function render() {
    if (toggle) {
      toggle.setAttribute("aria-pressed", String(enabled));
      toggle.setAttribute("aria-label", enabled ? "Voz activada: tocar para silenciar" : "Voz silenciada: tocar para activar");
      toggle.title = enabled ? "Respuestas en voz alta (activado)" : "Respuestas en voz alta (silenciado)";
    }
    if (stopButton) stopButton.hidden = !current && queue.length === 0;
  }

  function toUrl(base64) {
    const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
    return URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
  }

  function playNext() {
    if (current || queue.length === 0) {
      render();
      return;
    }
    const url = queue.shift();
    current = new Audio(url);
    const done = () => {
      URL.revokeObjectURL(url);
      current = null;
      playNext();
    };
    current.addEventListener("ended", done);
    current.addEventListener("error", done);
    current.play().catch(done); // si el navegador bloquea el audio, se pasa a la siguiente
    render();
  }

  function enqueue(base64) {
    if (!enabled) return;
    queue.push(toUrl(base64));
    playNext();
  }

  function playUrl(url) {
    stop();
    queue.push(url);
    playNext();
  }

  function stop() {
    queue.splice(0).forEach((url) => URL.revokeObjectURL(url));
    if (current) {
      current.pause();
      current = null;
    }
    render();
  }

  if (toggle) {
    toggle.addEventListener("click", () => {
      enabled = !enabled;
      try {
        localStorage.setItem(KEY, enabled ? "on" : "off");
      } catch (_) {}
      if (!enabled) stop();
      render();
    });
  }
  if (stopButton) stopButton.addEventListener("click", stop);

  window.JarvisSpeaker = {
    enqueue: enqueue,
    playUrl: playUrl,
    stop: stop,
    enabled: () => enabled,
    speaking: () => Boolean(current) || queue.length > 0,
  };
  render();
})();
