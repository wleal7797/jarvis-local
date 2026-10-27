/* Avisos en vivo (Etapa 13): cuando vence un recordatorio, aparece aquí y se dice en voz alta.
 *
 * Cada usuario sólo recibe los suyos (/ws/avisos). Si el agente de voz del PC está encendido
 * y esta página es del dueño, el aviso ya suena por los parlantes del PC: aquí sólo se muestra.
 */
(function () {
  "use strict";

  const box = document.getElementById("avisos");
  if (!box) return;
  let retry = 1000;

  async function speak(text) {
    if (window.JarvisAgentOn) return; // ya lo dice el agente de voz por los parlantes del PC
    try {
      const response = await fetch("/api/voice/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text }),
      });
      if (response.ok && window.JarvisSpeaker) {
        window.JarvisSpeaker.playUrl(URL.createObjectURL(await response.blob()));
      }
    } catch (_) { /* sin voz, el aviso igual se ve */ }
  }

  function show(notice) {
    const card = document.createElement("div");
    card.className = "aviso" + (notice.late ? " aviso--tarde" : "");
    card.setAttribute("role", "alert");
    const title = document.createElement("strong");
    title.textContent = notice.late ? "Recordatorio pendiente" : "Recordatorio";
    const text = document.createElement("span");
    text.textContent = notice.text;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "aviso__cerrar";
    close.setAttribute("aria-label", "Cerrar aviso");
    close.textContent = "×";
    close.addEventListener("click", () => card.remove());
    card.append(title, text, close);
    box.appendChild(card);
    if ("vibrate" in navigator) navigator.vibrate([200, 100, 200]);
    speak(notice.say || notice.text);
  }

  function connect() {
    const scheme = location.protocol === "https:" ? "wss://" : "ws://";
    const ws = new WebSocket(scheme + location.host + "/ws/avisos");
    ws.addEventListener("open", () => { retry = 1000; });
    ws.addEventListener("message", (event) => {
      const notice = JSON.parse(event.data);
      if (notice.type === "recordatorio") show(notice);
    });
    ws.addEventListener("close", () => {
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 30000);
    });
  }

  connect();
})();
