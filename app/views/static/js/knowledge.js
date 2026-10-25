/* Panel de Conocimiento: agregar archivos, páginas web y Wikipedia; ver tareas y fuentes. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const STATUS = {
    queued: "En cola",
    running: "Procesando",
    done: "Terminada",
    failed: "Falló",
    cancelled: "Cancelada",
  };
  const KIND = { file: "Archivo", web: "Web", wikipedia: "Wikipedia", manual: "Notas" };
  let pollTimer = null;
  let selectedFile = null;

  function fmt(n) {
    return new Intl.NumberFormat("es-CO").format(n);
  }

  function message(text, isError) {
    const el = $("form-message");
    el.textContent = text;
    el.classList.toggle("is-error", Boolean(isError));
  }

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

  // ---------- Pestañas ----------

  const tabs = ["file", "web", "wiki"];
  tabs.forEach((name) => {
    $("tab-" + name).addEventListener("click", () => {
      tabs.forEach((other) => {
        $("tab-" + other).setAttribute("aria-selected", String(other === name));
        $("panel-" + other).hidden = other !== name;
      });
      message("");
    });
  });

  // ---------- Archivo ----------

  function chooseFile(file) {
    selectedFile = file || null;
    $("drop-text").textContent = file ? file.name + " · " + Math.ceil(file.size / 1024) + " KB" : "Arrastra un archivo aquí o elígelo";
    $("file-submit").disabled = !file;
  }

  $("file-input").addEventListener("change", (e) => chooseFile(e.target.files[0]));
  const drop = $("drop");
  ["dragenter", "dragover"].forEach((ev) =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add("is-over");
    })
  );
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("is-over")));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    chooseFile(e.dataTransfer.files[0]);
  });

  $("panel-file").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!selectedFile) return;
    const form = new FormData();
    form.append("file", selectedFile);
    form.append("personal", $("file-personal").checked ? "true" : "false");
    await submit(() => api("/api/knowledge/files", { method: "POST", body: form }), "Archivo en cola.");
    chooseFile(null);
    $("file-input").value = "";
  });

  // ---------- Web ----------

  $("panel-web").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { url: $("web-url").value.trim(), max_pages: Number($("web-pages").value) || 1 };
    await submit(() => postJson("/api/knowledge/web", body), "Página en cola.");
  });

  // ---------- Wikipedia ----------

  $("panel-wiki").addEventListener("submit", async (e) => {
    e.preventDefault();
    const titles = $("wiki-titles").value.split("\n").map((t) => t.trim()).filter(Boolean);
    const category = $("wiki-category").value.trim() || null;
    if (!titles.length && !category) {
      message("Escribe al menos un artículo o una categoría.", true);
      return;
    }
    const body = { titles: titles, category: category, limit: Number($("wiki-limit").value) || 30 };
    await submit(() => postJson("/api/knowledge/wikipedia", body), "Artículos en cola.");
  });

  function postJson(url, body) {
    return api(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  async function submit(action, okText) {
    try {
      await action();
      message(okText + " El worker la procesará en segundo plano.");
      refresh();
    } catch (err) {
      message("No se pudo agregar: " + err.message, true);
    }
  }

  // ---------- Tareas ----------

  function renderJobs(jobs) {
    const list = $("jobs");
    list.replaceChildren();
    $("jobs-empty").hidden = jobs.length > 0;
    const pending = jobs.some((j) => j.status === "queued" || j.status === "running");
    $("worker-hint").hidden = !jobs.some((j) => j.status === "queued");

    jobs.forEach((job) => {
      const li = document.createElement("li");
      li.className = "job job--" + job.status;

      const head = document.createElement("div");
      head.className = "job__head";
      const kind = document.createElement("span");
      kind.className = "badge";
      kind.textContent = KIND[job.type] || job.type;
      const label = document.createElement("span");
      label.className = "job__label";
      label.textContent = job.label;
      label.title = job.label;
      const state = document.createElement("span");
      state.className = "job__status";
      state.textContent = STATUS[job.status] || job.status;
      head.append(kind, label, state);

      if (job.status === "queued" || job.status === "running") {
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "link-btn";
        cancel.textContent = "Cancelar";
        cancel.addEventListener("click", async () => {
          await api("/api/knowledge/jobs/" + job.id + "/cancel", { method: "POST" }).catch(() => {});
          refresh();
        });
        head.appendChild(cancel);
      }
      li.appendChild(head);

      const progress = document.createElement("div");
      progress.className = "job__progress";
      const bar = document.createElement("progress");
      bar.max = Math.max(job.docs_total, 1);
      if (job.status === "running" && job.docs_total === 0) bar.removeAttribute("value");
      else bar.value = job.status === "done" ? bar.max : job.docs_done;
      const count = document.createElement("span");
      count.textContent = fmt(job.docs_done) + " documento" + (job.docs_done === 1 ? "" : "s");
      progress.append(bar, count);
      li.appendChild(progress);

      if (job.error_message) {
        const err = document.createElement("p");
        err.className = "job__error";
        err.textContent = job.error_message;
        li.appendChild(err);
      }
      list.appendChild(li);
    });

    clearTimeout(pollTimer);
    if (pending) pollTimer = setTimeout(refresh, 3000);
  }

  // ---------- Fuentes ----------

  function renderSources(sources) {
    const list = $("sources");
    list.replaceChildren();
    $("sources-empty").hidden = sources.length > 0;
    let docs = 0;
    let chunks = 0;
    sources.forEach((s) => {
      docs += s.documents;
      chunks += s.chunks;
      const li = document.createElement("li");
      li.className = "source";
      const info = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = s.name;
      const meta = document.createElement("span");
      meta.className = "source__meta";
      meta.textContent =
        (KIND[s.kind] || s.kind) + " · " + fmt(s.documents) + " documentos · " + fmt(s.chunks) + " fragmentos" + (s.is_personal ? " · personal" : "");
      info.append(name, meta);
      const del = document.createElement("button");
      del.type = "button";
      del.className = "link-btn link-btn--danger";
      del.textContent = "Borrar";
      del.addEventListener("click", async () => {
        if (!confirm('¿Borrar "' + s.name + '" y todo lo que JARVIS aprendió de ella?')) return;
        await api("/api/knowledge/sources/" + s.id, { method: "DELETE" }).catch((err) => alert(err.message));
        refresh();
      });
      li.append(info, del);
      list.appendChild(li);
    });
    $("stat-sources").textContent = fmt(sources.length);
    $("stat-documents").textContent = fmt(docs);
    $("stat-chunks").textContent = fmt(chunks);
  }

  // ---------- Búsqueda de prueba ----------

  $("search-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("search-input").value.trim();
    const list = $("results");
    list.replaceChildren();
    try {
      const results = await api("/api/knowledge/search?q=" + encodeURIComponent(q));
      if (!results.length) {
        const li = document.createElement("li");
        li.className = "empty";
        li.textContent = "Nada relevante: JARVIS respondería sin documentos.";
        list.appendChild(li);
      }
      results.forEach((r) => {
        const li = document.createElement("li");
        const head = document.createElement("strong");
        head.textContent = [r.title, r.section].filter(Boolean).join(" › ");
        const score = document.createElement("span");
        score.className = "sources__score";
        score.textContent = r.similarity != null ? Math.round(r.similarity * 100) + " %" : "";
        const text = document.createElement("p");
        text.textContent = r.content.length > 320 ? r.content.slice(0, 320) + "…" : r.content;
        li.append(head, score, text);
        list.appendChild(li);
      });
    } catch (err) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = err.message;
      list.appendChild(li);
    }
  });

  // ---------- Inicio ----------

  async function refresh() {
    try {
      const [jobs, sources] = await Promise.all([api("/api/knowledge/jobs"), api("/api/knowledge/sources")]);
      renderJobs(jobs);
      renderSources(sources);
    } catch (err) {
      message("No se pudo cargar: " + err.message, true);
    }
  }

  refresh();
})();
