/* Entrar a JARVIS (o, la primera vez, elegir la contraseña del dueño). */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const login = $("login-form");
  const setup = $("setup-form");
  const message = $("login-message");

  function say(text, isError) {
    message.textContent = text || "";
    message.classList.toggle("is-error", Boolean(isError));
  }

  function next() {
    const target = new URLSearchParams(location.search).get("next") || "/";
    // Sólo rutas de este mismo sitio (evita redirigir a otra página).
    return target.startsWith("/") && !target.startsWith("//") ? target : "/";
  }

  async function post(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let data = {};
    try { data = await response.json(); } catch (_) { /* sin cuerpo */ }
    if (!response.ok) throw new Error(data.detail || "No se pudo entrar.");
    return data;
  }

  login.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = login.querySelector("button");
    button.disabled = true;
    say("Entrando…");
    try {
      await post("/api/auth/login", { username: $("username").value.trim(), password: $("password").value });
      location.replace(next());
    } catch (err) {
      say(err.message, true);
      $("password").select();
    } finally {
      button.disabled = false;
    }
  });

  setup.addEventListener("submit", async (event) => {
    event.preventDefault();
    if ($("setup-password").value !== $("setup-repeat").value) {
      say("Las contraseñas no coinciden.", true);
      return;
    }
    try {
      await post("/api/auth/setup", { password: $("setup-password").value });
      location.replace("/");
    } catch (err) {
      say(err.message, true);
    }
  });

  fetch("/api/auth/me")
    .then((r) => r.json())
    .then((me) => {
      if (me.needs_setup) {
        setup.hidden = false;
        $("setup-password").focus();
      } else {
        login.hidden = false;
        $("username").focus();
      }
    })
    .catch(() => {
      login.hidden = false;
      say("No se pudo conectar con JARVIS.", true);
    });
})();
