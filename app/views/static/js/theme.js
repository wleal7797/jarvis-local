/* Botón de tema claro/oscuro, compartido por todas las páginas. */
(function () {
  "use strict";
  const button = document.getElementById("toggle-theme");
  if (!button) return;

  function currentTheme() {
    const forced = document.documentElement.dataset.theme;
    if (forced) return forced;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  button.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("jarvis-theme", next);
    } catch (_) {}
  });
})();
