/* Página "Usuarios" (sólo el dueño): agregar, cambiar rol, contraseña o desactivar. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const list = $("users");
  const form = $("user-form");
  const message = $("users-message");
  const ROLES = { owner: "Dueño", member: "Familia", guest: "Invitado" };
  const me = window.JARVIS_ME;

  function say(text, isError) {
    message.textContent = text || "";
    message.classList.toggle("is-error", Boolean(isError));
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    let body = null;
    try { body = await response.json(); } catch (_) { /* sin cuerpo */ }
    if (!response.ok) {
      const detail = body && body.detail;
      throw new Error(typeof detail === "string" ? detail : "La petición falló.");
    }
    return body;
  }

  function patch(id, data) {
    return api("/api/users/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  }

  function item(u) {
    const li = document.createElement("li");
    li.className = "user" + (u.is_active ? "" : " user--off");

    const who = document.createElement("div");
    who.className = "user__who";
    const name = document.createElement("strong");
    name.textContent = u.display_name;
    const handle = document.createElement("span");
    handle.textContent = "@" + u.username + (u.id === me ? " · usted" : "") + (u.is_active ? "" : " · desactivado");
    who.append(name, handle);

    const role = document.createElement("select");
    role.setAttribute("aria-label", "Rol de " + u.display_name);
    Object.entries(ROLES).forEach(([value, label]) => {
      const option = new Option(label, value, false, value === u.role);
      role.appendChild(option);
    });
    role.disabled = u.id === me;
    role.addEventListener("change", async () => {
      try {
        await patch(u.id, { role: role.value });
        say("Rol actualizado.");
      } catch (err) {
        say(err.message, true);
        load();
      }
    });

    const actions = document.createElement("div");
    actions.className = "user__actions";
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "btn";
    reset.textContent = "Cambiar contraseña";
    reset.addEventListener("click", async () => {
      const password = prompt("Contraseña nueva para " + u.display_name + " (mínimo 8 caracteres):");
      if (!password) return;
      try {
        await patch(u.id, { password: password });
        say("Contraseña cambiada.");
      } catch (err) {
        say(err.message, true);
      }
    });
    actions.appendChild(reset);
    if (u.id !== me) {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "btn" + (u.is_active ? " btn--danger" : "");
      toggle.textContent = u.is_active ? "Desactivar" : "Activar";
      toggle.addEventListener("click", async () => {
        try {
          await patch(u.id, { is_active: !u.is_active });
          load();
        } catch (err) {
          say(err.message, true);
        }
      });
      actions.appendChild(toggle);
    }

    li.append(who, role, actions);
    return li;
  }

  async function load() {
    try {
      const users = await api("/api/users");
      list.replaceChildren(...users.map(item));
    } catch (err) {
      say("No se pudo cargar la lista: " + err.message, true);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: $("new-name").value.trim(),
          username: $("new-username").value.trim().toLowerCase(),
          password: $("new-password").value,
          role: $("new-role").value,
        }),
      });
      say("Listo. Ya puede entrar desde su dispositivo.");
      form.reset();
      load();
    } catch (err) {
      say(err.message, true);
    }
  });

  load();
})();
