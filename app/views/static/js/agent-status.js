/* Qué está haciendo el agente de voz del PC ("Jarvis, …" sin tocar nada).
 *
 * La API empuja cada cambio por /ws/voice-status: le escucho → pensando → hablando →
 * le sigo escuchando → en espera. Si el agente deja de dar señales 6 minutos, se oculta.
 */
(function () {
  "use strict";

  const box = document.getElementById("agent-status");
  if (!box) return;
  const label = box.querySelector(".agent__text");
  const STALE_MS = 6 * 60 * 1000;
  const TEXTS = {
    en_espera: "Micrófono atento · diga «Jarvis, …»",
    escuchando: "Le escucho…",
    pensando: "Pensando",
    buscando: "Consultando sus documentos",
    hablando: "Hablando",
    atento: "Le sigo escuchando…",
  };
  let last = { state: "apagado", at: 0 };
  let retry = 1000;

  function quote(text) {
    const short = text.length > 70 ? text.slice(0, 69) + "…" : text;
    return short ? " · «" + short + "»" : "";
  }

  function render() {
    const fresh = Date.now() - last.at * 1000 < STALE_MS;
    const known = Object.prototype.hasOwnProperty.call(TEXTS, last.state);
    box.hidden = !(fresh && known);
    // avisos.js: si el agente está encendido, los recordatorios ya suenan por el PC.
    window.JarvisAgentOn = !box.hidden;
    if (box.hidden) return;
    box.dataset.state = last.state;
    const withText = ["pensando", "buscando", "hablando"].indexOf(last.state) !== -1;
    label.textContent = TEXTS[last.state] + (withText ? quote(last.text || "") : "");
  }

  function connect() {
    const scheme = location.protocol === "https:" ? "wss://" : "ws://";
    const ws = new WebSocket(scheme + location.host + "/ws/voice-status");
    ws.addEventListener("open", () => { retry = 1000; });
    ws.addEventListener("message", (event) => {
      const previous = last.state;
      last = JSON.parse(event.data);
      render();
      // Terminó de responder por voz: la conversación nueva aparece en la lista.
      if (["pensando", "buscando", "hablando"].indexOf(previous) !== -1 && last.state !== "hablando" && last.state !== "buscando") {
        if (window.JarvisChat && window.JarvisChat.refresh) window.JarvisChat.refresh();
      }
    });
    ws.addEventListener("close", () => {
      box.hidden = true;
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 15000);
    });
  }

  setInterval(render, 30000); // para ocultarlo si el agente se cerró a la fuerza
  connect();
})();
