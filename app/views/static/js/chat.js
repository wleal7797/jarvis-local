/* Chat en vivo de JARVIS.
 *
 * - Envía los mensajes por WebSocket (/ws/chat) y pinta la respuesta palabra por palabra.
 * - Lista, abre y borra conversaciones con la API REST (/api/conversations).
 * - Revisa cada 30 s el estado de Ollama y PostgreSQL (/health).
 * - Recuerda la conversación abierta en la URL (#c=ID) y el tema en localStorage.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const els = {
    sidebar: $("sidebar"),
    scrim: $("scrim"),
    openSidebar: $("open-sidebar"),
    newChat: $("new-chat"),
    list: $("conversations-list"),
    listEmpty: $("conversations-empty"),
    title: $("chat-title"),
    status: $("status"),
    toggleTheme: $("toggle-theme"),
    messages: $("messages"),
    messagesList: $("messages-list"),
    welcome: $("welcome"),
    greeting: $("greeting"),
    form: $("composer"),
    input: $("input"),
    send: $("send"),
  };

  const state = {
    ws: null,
    connected: false,
    conversationId: null,
    busy: false,
    reply: null, // { el, text, started }
    retryMs: 1000,
  };

  // ---------- Utilidades ----------

  function greetingForNow() {
    const hour = new Date().getHours();
    if (hour < 12) return "Buenos días. ¿En qué puedo ayudarle?";
    if (hour < 19) return "Buenas tardes. ¿En qué puedo ayudarle?";
    return "Buenas noches. ¿En qué puedo ayudarle?";
  }

  function nearBottom() {
    const m = els.messages;
    return m.scrollHeight - m.scrollTop - m.clientHeight < 120;
  }

  function scrollToBottom(force) {
    if (force || nearBottom()) els.messages.scrollTop = els.messages.scrollHeight;
  }

  function formatMeta(end) {
    const parts = [];
    if (end.latency_ms != null) parts.push((end.latency_ms / 1000).toFixed(1).replace(".", ",") + " s");
    if (end.tokens_per_second != null) parts.push(String(end.tokens_per_second).replace(".", ",") + " tok/s");
    return parts.join(" · ");
  }

  function setWelcome(visible) {
    els.welcome.hidden = !visible;
  }

  function updateSendButton() {
    els.send.disabled = state.busy || !state.connected || els.input.value.trim() === "";
  }

  function autoGrow() {
    els.input.style.height = "auto";
    els.input.style.height = Math.min(els.input.scrollHeight, 180) + "px";
  }

  // ---------- Mensajes en pantalla ----------

  function addMessage(role, text, meta) {
    setWelcome(false);
    const wrap = document.createElement("article");
    wrap.className = "msg msg--" + role;
    if (role === "assistant" || role === "error") {
      const who = document.createElement("span");
      who.className = "msg__who";
      who.textContent = "JARVIS";
      wrap.appendChild(who);
    }
    const bubble = document.createElement("div");
    bubble.className = "msg__bubble";
    if (role === "user") bubble.textContent = text;
    else bubble.innerHTML = window.JarvisMarkdown.render(text || "");
    wrap.appendChild(bubble);
    const metaEl = document.createElement("span");
    metaEl.className = "msg__meta";
    metaEl.textContent = meta || "";
    wrap.appendChild(metaEl);
    els.messagesList.appendChild(wrap);
    return { wrap: wrap, bubble: bubble, meta: metaEl };
  }

  // Fuentes consultadas: las citadas en la respuesta ([1], [2]…) se resaltan.
  function renderSources(wrap, sources, text) {
    if (!sources || !sources.length) return;
    const cited = new Set((text.match(/\[(\d{1,2})\]/g) || []).map((m) => Number(m.slice(1, -1))));
    const details = document.createElement("details");
    details.className = "sources";
    const summary = document.createElement("summary");
    summary.textContent = cited.size
      ? "Fuentes citadas: " + cited.size + " de " + sources.length
      : "Documentos consultados: " + sources.length;
    details.appendChild(summary);
    const list = document.createElement("ol");
    sources.forEach((s) => {
      const li = document.createElement("li");
      li.value = s.n;
      if (cited.has(s.n)) li.className = "is-cited";
      const label = [s.title, s.section].filter(Boolean).join(" › ");
      li.textContent = label || "Documento " + s.n;
      if (s.similarity != null) {
        const score = document.createElement("span");
        score.className = "sources__score";
        score.textContent = Math.round(s.similarity * 100) + " %";
        score.title = "Parecido con la pregunta";
        li.appendChild(score);
      }
      list.appendChild(li);
    });
    details.appendChild(list);
    wrap.insertBefore(details, wrap.querySelector(".msg__meta"));
  }

  function startReply() {
    const reply = addMessage("assistant", "");
    reply.bubble.innerHTML = '<span class="typing" aria-label="JARVIS está escribiendo"><span></span><span></span><span></span></span>';
    state.reply = { el: reply, text: "", frame: null, wakeTimer: null };
    // Si el modelo estaba descargado de la GPU, la primera palabra tarda ~10 s: avisarlo.
    state.reply.wakeTimer = setTimeout(() => {
      if (state.reply && state.reply.text === "") {
        reply.bubble.insertAdjacentHTML(
          "beforeend",
          '<span class="waking">Despertando el modelo… la primera respuesta tarda unos segundos.</span>'
        );
        scrollToBottom(false);
      }
    }, 3000);
    scrollToBottom(true);
  }

  function clearWakeTimer() {
    if (state.reply && state.reply.wakeTimer) clearTimeout(state.reply.wakeTimer);
  }

  function appendToken(content) {
    const reply = state.reply;
    if (!reply) return;
    clearWakeTimer();
    reply.text += content;
    // Repinta como máximo una vez por cuadro de animación.
    if (reply.frame) return;
    reply.frame = requestAnimationFrame(() => {
      reply.frame = null;
      const stick = nearBottom();
      reply.el.bubble.innerHTML = window.JarvisMarkdown.render(reply.text);
      if (stick) scrollToBottom(true);
    });
  }

  function finishReply(end) {
    if (!state.reply) return;
    clearWakeTimer();
    if (state.reply.frame) cancelAnimationFrame(state.reply.frame);
    state.reply.el.bubble.innerHTML = window.JarvisMarkdown.render(state.reply.text.trim());
    state.reply.el.meta.textContent = formatMeta(end);
    renderSources(state.reply.el.wrap, state.reply.sources, state.reply.text);
    state.reply = null;
    setBusy(false);
    loadConversations();
  }

  function failReply(message) {
    clearWakeTimer();
    if (state.reply) {
      state.reply.el.wrap.className = "msg msg--error";
      state.reply.el.bubble.textContent = message;
      state.reply = null;
    } else {
      addMessage("error", message);
    }
    setBusy(false);
  }

  function setBusy(busy) {
    state.busy = busy;
    updateSendButton();
    if (!busy) els.input.focus();
  }

  // ---------- WebSocket ----------

  function connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(scheme + "://" + location.host + "/ws/chat");
    state.ws = ws;

    ws.addEventListener("open", () => {
      state.connected = true;
      state.retryMs = 1000;
      updateSendButton();
      checkHealth();
    });

    ws.addEventListener("message", (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "start") {
        const isNew = state.conversationId !== data.conversation_id;
        state.conversationId = data.conversation_id;
        if (isNew) history.replaceState(null, "", "#c=" + data.conversation_id);
      } else if (data.type === "sources") {
        if (state.reply) {
          state.reply.sources = data.sources;
          if (state.reply.text === "") {
            clearWakeTimer();
            const n = data.sources.length;
            state.reply.el.bubble.insertAdjacentHTML(
              "beforeend",
              '<span class="waking">Consultando ' + n + (n === 1 ? " documento…" : " documentos…") + "</span>"
            );
          }
        }
      } else if (data.type === "token") {
        appendToken(data.content);
      } else if (data.type === "end") {
        finishReply(data);
      } else if (data.type === "error") {
        failReply(data.message || "Algo salió mal.");
      }
    });

    ws.addEventListener("close", () => {
      state.connected = false;
      updateSendButton();
      if (state.busy) failReply("Se perdió la conexión con JARVIS.");
      setStatus("down", "Sin conexión");
      // Reintenta con espera creciente (máximo 10 s).
      setTimeout(connect, state.retryMs);
      state.retryMs = Math.min(state.retryMs * 2, 10000);
    });
  }

  function sendMessage(text) {
    const message = text.trim();
    if (!message || state.busy || !state.connected) return;
    addMessage("user", message);
    if (!state.conversationId) els.title.textContent = message.slice(0, 60);
    startReply();
    setBusy(true);
    state.ws.send(JSON.stringify({ message: message, conversation_id: state.conversationId }));
    els.input.value = "";
    autoGrow();
    updateSendButton();
  }

  // ---------- Conversaciones ----------

  async function loadConversations() {
    try {
      const response = await fetch("/api/conversations");
      if (!response.ok) throw new Error(response.status);
      renderConversations(await response.json());
    } catch (_) {
      els.listEmpty.textContent = "No se pudo cargar el historial.";
      els.listEmpty.hidden = false;
    }
  }

  function renderConversations(items) {
    els.list.replaceChildren();
    els.listEmpty.hidden = items.length > 0;
    els.listEmpty.textContent = "Aún no hay conversaciones.";
    items.forEach((conv) => {
      const li = document.createElement("li");
      li.className = "conv";
      if (conv.id === state.conversationId) {
        li.setAttribute("aria-current", "true");
        if (conv.title) els.title.textContent = conv.title;
      }

      const open = document.createElement("button");
      open.type = "button";
      open.className = "conv__open";
      open.textContent = conv.title || "Sin título";
      open.title = conv.title || "";
      open.addEventListener("click", () => openConversation(conv.id, conv.title));

      const del = document.createElement("button");
      del.type = "button";
      del.className = "conv__delete";
      del.setAttribute("aria-label", "Borrar conversación: " + (conv.title || ""));
      del.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';
      del.addEventListener("click", () => deleteConversation(conv.id, conv.title));

      li.append(open, del);
      els.list.appendChild(li);
    });
  }

  async function openConversation(id, title) {
    if (state.busy) return;
    closeSidebar();
    try {
      const response = await fetch("/api/conversations/" + id + "/messages");
      if (!response.ok) throw new Error(response.status);
      const messages = await response.json();
      state.conversationId = id;
      history.replaceState(null, "", "#c=" + id);
      els.title.textContent = title || "Conversación";
      els.messagesList.replaceChildren();
      setWelcome(messages.length === 0);
      messages.forEach((m) => {
        const meta = m.role === "assistant" ? formatMeta({ latency_ms: m.latency_ms }) : "";
        const added = addMessage(m.role === "user" ? "user" : "assistant", m.content, meta);
        if (m.role === "assistant") renderSources(added.wrap, m.sources, m.content);
      });
      scrollToBottom(true);
      loadConversations();
    } catch (_) {
      newConversation();
    }
  }

  async function deleteConversation(id, title) {
    if (!confirm('¿Borrar la conversación "' + (title || "Sin título") + '"? No se puede deshacer.')) return;
    const response = await fetch("/api/conversations/" + id, { method: "DELETE" });
    if (response.ok && id === state.conversationId) newConversation();
    loadConversations();
  }

  function newConversation() {
    if (state.busy) return;
    state.conversationId = null;
    history.replaceState(null, "", location.pathname);
    els.title.textContent = "Nueva conversación";
    els.messagesList.replaceChildren();
    els.greeting.textContent = greetingForNow();
    setWelcome(true);
    closeSidebar();
    loadConversations();
    els.input.focus();
  }

  // ---------- Estado de los servicios ----------

  function setStatus(stateName, text) {
    els.status.dataset.state = stateName;
    els.status.querySelector(".status__text").textContent = text;
    els.status.title = text;
  }

  async function checkHealth() {
    try {
      const response = await fetch("/health");
      const body = await response.json();
      const deps = body.dependencies || {};
      const down = Object.keys(deps).filter((k) => deps[k].status !== "up");
      if (body.status === "ok") setStatus("ok", "En línea");
      else setStatus("degraded", "Sin " + down.map((d) => (d === "ollama" ? "modelo" : "base de datos")).join(" ni "));
    } catch (_) {
      setStatus("down", "Sin conexión");
    }
  }

  // ---------- Barra lateral en celular ----------

  function openSidebar() {
    els.sidebar.classList.add("is-open");
    els.scrim.hidden = false;
    els.openSidebar.setAttribute("aria-expanded", "true");
  }

  function closeSidebar() {
    els.sidebar.classList.remove("is-open");
    els.scrim.hidden = true;
    els.openSidebar.setAttribute("aria-expanded", "false");
  }

  // ---------- Tema ----------

  function currentTheme() {
    const forced = document.documentElement.dataset.theme;
    if (forced) return forced;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function toggleTheme() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("jarvis-theme", next);
    } catch (_) {}
  }

  // ---------- Eventos ----------

  els.form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(els.input.value);
  });
  els.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      sendMessage(els.input.value);
    }
  });
  els.input.addEventListener("input", () => {
    autoGrow();
    updateSendButton();
  });
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => sendMessage(chip.dataset.prompt));
  });
  els.newChat.addEventListener("click", newConversation);
  els.openSidebar.addEventListener("click", openSidebar);
  els.scrim.addEventListener("click", closeSidebar);
  els.toggleTheme.addEventListener("click", toggleTheme);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSidebar();
  });

  // ---------- Inicio ----------

  els.greeting.textContent = greetingForNow();
  connect();
  loadConversations();
  setInterval(checkHealth, 30000);

  const match = location.hash.match(/^#c=(\d+)$/);
  if (match) openConversation(Number(match[1]), "");
  els.input.focus();
})();
