/* Convierte el Markdown básico de las respuestas en HTML seguro.
 *
 * Primero escapa TODO el texto (así el modelo nunca puede inyectar HTML) y después
 * aplica un subconjunto pequeño: párrafos, listas, **negrita**, *cursiva*, `código`
 * y bloques ``` ```. Sin librerías externas: la página funciona sin internet.
 */
(function () {
  "use strict";

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function inline(text) {
    return text
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  }

  function render(source) {
    const parts = escapeHtml(source).split(/```[a-zA-Z0-9_-]*\n?/);
    let html = "";
    parts.forEach(function (part, index) {
      // Las posiciones impares están dentro de un bloque de código.
      if (index % 2 === 1) {
        html += "<pre><code>" + part.replace(/\n$/, "") + "</code></pre>";
        return;
      }
      html += renderBlocks(part);
    });
    return html;
  }

  function renderBlocks(text) {
    const lines = text.split("\n");
    let html = "";
    let paragraph = [];
    let list = null; // "ul" | "ol"

    function flushParagraph() {
      if (paragraph.length) {
        html += "<p>" + inline(paragraph.join("<br>")) + "</p>";
        paragraph = [];
      }
    }
    function closeList() {
      if (list) {
        html += "</" + list + ">";
        list = null;
      }
    }

    lines.forEach(function (raw) {
      const line = raw.trim();
      const bullet = line.match(/^[-*•]\s+(.*)$/);
      const numbered = line.match(/^\d+[.)]\s+(.*)$/);
      if (bullet || numbered) {
        flushParagraph();
        const type = bullet ? "ul" : "ol";
        if (list !== type) {
          closeList();
          html += "<" + type + ">";
          list = type;
        }
        html += "<li>" + inline((bullet || numbered)[1]) + "</li>";
      } else if (line === "") {
        flushParagraph();
        closeList();
      } else {
        closeList();
        paragraph.push(line);
      }
    });
    flushParagraph();
    closeList();
    return html;
  }

  window.JarvisMarkdown = { render: render, escapeHtml: escapeHtml };
})();
