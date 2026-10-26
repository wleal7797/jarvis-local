/* Calificar respuestas (👍 / 👎 con corrección) y avisar lo que JARVIS aprendió.
 *
 * - 👍 / 👎 quedan guardados (PUT /api/messages/{id}/feedback).
 * - Con 👎 se puede escribir la respuesta correcta: se vuelve un ejemplo de entrenamiento
 *   para ajustar el modelo en la Etapa 12.
 * - Cuando JARVIS guarda un recuerdo, aparece una nota bajo la respuesta.
 */
(function () {
  "use strict";

  const UP = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M7 10v12M15 5.9 14 10h5.8a2 2 0 0 1 1.9 2.6l-2.3 8a2 2 0 0 1-1.9 1.4H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.8a2 2 0 0 0 1.8-1.1L12 2a3.1 3.1 0 0 1 3 3.9Z"/></svg>';
  const DOWN = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M17 14V2M9 18.1 10 14H4.2a2 2 0 0 1-1.9-2.6l2.3-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.8a2 2 0 0 0-1.8 1.1L12 22a3.1 3.1 0 0 1-3-3.9Z"/></svg>';
  const MEMORY = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 3a6 6 0 0 0-6 6c0 2.2 1.2 3.6 2.2 4.6.7.7 1.3 1.6 1.3 2.6V18h5v-1.8c0-1 .6-1.9 1.3-2.6 1-1 2.2-2.4 2.2-4.6a6 6 0 0 0-6-6ZM10 21h4"/></svg>';

  async function save(messageId, rating, correction) {
    const response = await fetch("/api/messages/" + messageId + "/feedback", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating: rating, correction: correction || null }),
    });
    if (!response.ok) throw new Error(response.status);
    return response.json();
  }

  function button(html, label) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "rate-btn";
    b.innerHTML = html;
    b.setAttribute("aria-label", label);
    b.title = label;
    b.setAttribute("aria-pressed", "false");
    return b;
  }

  /* Agrega 👍 / 👎 a una respuesta ya terminada. `el` = {wrap, bubble, meta}. */
  function attach(el, messageId, rating) {
    if (!messageId || el.wrap.querySelector(".rate")) return;
    const box = document.createElement("span");
    box.className = "rate";
    const up = button(UP, "Buena respuesta");
    const down = button(DOWN, "Mala respuesta: corregirla");
    box.append(up, down);
    el.meta.append(" · ", box);

    function show(value) {
      up.setAttribute("aria-pressed", String(value === 1));
      down.setAttribute("aria-pressed", String(value === -1));
    }
    show(rating);

    up.addEventListener("click", async () => {
      closeForm(el);
      try {
        await save(messageId, 1);
        show(1);
      } catch (_) {
        up.title = "No se pudo guardar";
      }
    });
    down.addEventListener("click", async () => {
      try {
        await save(messageId, -1);
        show(-1);
        openForm(el, messageId);
      } catch (_) {
        down.title = "No se pudo guardar";
      }
    });
  }

  function closeForm(el) {
    const form = el.wrap.querySelector(".correction");
    if (form) form.remove();
  }

  function openForm(el, messageId) {
    if (el.wrap.querySelector(".correction")) return;
    const form = document.createElement("form");
    form.className = "correction";
    form.innerHTML =
      '<label class="correction__label">¿Cuál era la respuesta correcta? <span>(opcional, para que aprenda)</span>' +
      '<textarea rows="3" maxlength="4000" placeholder="Escriba aquí la respuesta que esperaba…"></textarea></label>' +
      '<div class="correction__actions"><button class="btn" type="button" data-cancel>Ahora no</button>' +
      '<button class="btn btn--primary" type="submit">Guardar corrección</button></div>' +
      '<p class="correction__msg" role="status" aria-live="polite"></p>';
    el.wrap.insertBefore(form, el.meta.nextSibling);
    const textarea = form.querySelector("textarea");
    const message = form.querySelector(".correction__msg");
    textarea.focus();
    form.querySelector("[data-cancel]").addEventListener("click", () => form.remove());
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = textarea.value.trim();
      if (!text) {
        form.remove();
        return;
      }
      try {
        const result = await save(messageId, -1, text);
        message.textContent = result.training_example
          ? "Gracias. Guardé la corrección para aprender de ella."
          : "Gracias, quedó guardada.";
        textarea.disabled = true;
        form.querySelectorAll("button").forEach((b) => b.remove());
      } catch (_) {
        message.textContent = "No se pudo guardar. Intente de nuevo.";
      }
    });
  }

  /* Nota bajo la respuesta: "Lo recordaré: …". */
  function noteMemory(el, memory) {
    if (!el) return;
    const note = document.createElement("p");
    note.className = "msg__memory";
    note.innerHTML = MEMORY;
    const text = document.createElement("span");
    text.textContent = (memory.updated ? "Actualicé en mi memoria: " : "Lo recordaré: ") + memory.content + " ";
    const link = document.createElement("a");
    link.href = "/memoria";
    link.textContent = "Ver memoria";
    note.append(text, link);
    el.wrap.appendChild(note);
  }

  window.JarvisFeedback = { attach: attach, noteMemory: noteMemory };
})();
