/* Panel "Memoria": ver, agregar, corregir y borrar lo que JARVIS recuerda. */
(function () {
  "use strict";

  const list = document.getElementById("memories");
  const empty = document.getElementById("memories-empty");
  const count = document.getElementById("memories-count");
  const form = document.getElementById("memory-form");
  const input = document.getElementById("memory-content");
  const importance = document.getElementById("memory-importance");
  const message = document.getElementById("memory-message");
  const LEVELS = { 5: "Alta", 3: "Normal", 1: "Baja" };
  const dateFormat = new Intl.DateTimeFormat("es-CO", { day: "numeric", month: "short", year: "numeric" });

  function say(text, isError) {
    message.textContent = text || "";
    message.classList.toggle("is-error", Boolean(isError));
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    if (!response.ok) {
      let detail = response.statusText;
      try { detail = (await response.json()).detail || detail; } catch (_) { /* sin cuerpo */ }
      throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
  }

  function level(value) {
    if (value >= 5) return 5;
    if (value <= 1) return 1;
    return 3;
  }

  function render(memories) {
    list.replaceChildren();
    empty.hidden = memories.length > 0;
    count.textContent = memories.length ? memories.length + (memories.length === 1 ? " recuerdo" : " recuerdos") : "";
    memories.forEach((m) => list.appendChild(item(m)));
  }

  function item(m) {
    const li = document.createElement("li");
    li.className = "memory";

    const text = document.createElement("p");
    text.className = "memory__text";
    text.textContent = m.content;

    const meta = document.createElement("div");
    meta.className = "memory__meta";
    const badge = document.createElement("span");
    badge.className = "memory__level memory__level--" + level(m.importance);
    badge.textContent = LEVELS[level(m.importance)];
    const when = document.createElement("span");
    when.textContent = dateFormat.format(new Date(m.created_at)) + (m.source_message_id ? " · de una conversación" : " · agregado a mano");
    meta.append(badge, when);

    const actions = document.createElement("div");
    actions.className = "memory__actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "btn";
    edit.textContent = "Corregir";
    const forget = document.createElement("button");
    forget.type = "button";
    forget.className = "btn btn--danger";
    forget.textContent = "Olvidar";
    actions.append(edit, forget);

    edit.addEventListener("click", () => startEdit(li, m));
    forget.addEventListener("click", async () => {
      if (!confirm("¿Olvidar este recuerdo?\n\n" + m.content)) return;
      try {
        await api("/api/memories/" + m.id, { method: "DELETE" });
        say("Listo, lo olvidé.");
        load();
      } catch (err) {
        say("No se pudo borrar: " + err.message, true);
      }
    });

    li.append(text, meta, actions);
    return li;
  }

  function startEdit(li, m) {
    const editor = document.createElement("form");
    editor.className = "memory__edit";
    const field = document.createElement("input");
    field.type = "text";
    field.maxLength = 300;
    field.value = m.content;
    field.setAttribute("aria-label", "Recuerdo");
    const select = importance.cloneNode(true);
    select.id = "";
    select.value = String(level(m.importance));
    select.setAttribute("aria-label", "Importancia");
    const save = document.createElement("button");
    save.className = "btn btn--primary";
    save.type = "submit";
    save.textContent = "Guardar";
    const cancel = document.createElement("button");
    cancel.className = "btn";
    cancel.type = "button";
    cancel.textContent = "Cancelar";
    editor.append(field, select, save, cancel);
    li.replaceChildren(editor);
    field.focus();

    cancel.addEventListener("click", load);
    editor.addEventListener("submit", async (event) => {
      event.preventDefault();
      const content = field.value.trim();
      if (content.length < 3) return;
      save.disabled = true;
      save.textContent = "Guardando…";
      try {
        await api("/api/memories/" + m.id, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: content, importance: Number(select.value) }),
        });
        say("Recuerdo corregido.");
        load();
      } catch (err) {
        save.disabled = false;
        say("No se pudo guardar: " + err.message, true);
      }
    });
  }

  async function load() {
    try {
      render(await api("/api/memories"));
    } catch (err) {
      say("No se pudo cargar la memoria: " + err.message, true);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (content.length < 3) return;
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    say("Guardando…");
    try {
      const result = await api("/api/memories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: content, importance: Number(importance.value) }),
      });
      say(result.updated ? "Ya sabía algo parecido: lo actualicé." : "Guardado. Lo tendrá presente desde ahora.");
      input.value = "";
      load();
    } catch (err) {
      say("No se pudo guardar: " + err.message, true);
    } finally {
      button.disabled = false;
    }
  });

  load();
})();
