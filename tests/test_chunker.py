"""Pruebas del divisor de documentos en fragmentos."""

from app.services.chunker import chunk_text
from app.services.prompt_builder import estimate_tokens

DOC = """# Guía de la casa

Introducción general.

## Cocina

La estufa es de gas.

### Horno

El horno tarda 10 minutos en calentar.

## Jardín

Se riega los martes.
"""


def test_respeta_las_secciones_y_las_pone_como_encabezado():
    chunks = chunk_text(DOC, "Guía de la casa")
    sections = [c.section for c in chunks]
    assert sections == ["", "Cocina", "Cocina > Horno", "Jardín"]
    horno = chunks[2]
    assert horno.text.startswith("Guía de la casa > Cocina > Horno")
    assert "10 minutos" in horno.text
    # Una sección nunca se mezcla con otra.
    assert "martes" not in horno.text


def test_ningun_fragmento_pasa_del_limite_y_no_se_pierde_texto():
    paragraphs = [f"Párrafo número {i}. " + "palabra " * 60 for i in range(30)]
    text = "## Larga\n\n" + "\n\n".join(paragraphs)
    chunks = chunk_text(text, "Documento", max_tokens=200)

    assert len(chunks) > 5
    assert all(c.token_count <= 200 for c in chunks)
    joined = " ".join(c.text for c in chunks)
    assert all(f"Párrafo número {i}." in joined for i in range(30))


def test_fragmentos_seguidos_se_solapan():
    paragraphs = [f"Idea {i}: " + "texto " * 50 for i in range(6)]
    chunks = chunk_text("\n\n".join(paragraphs), "Doc", max_tokens=200)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        last_paragraph = previous.text.split("\n\n")[-1]
        assert last_paragraph in current.text


def test_parrafo_gigante_se_corta_por_lineas():
    table = "\n".join(f"| fila {i} | valor {i} |" for i in range(400))
    chunks = chunk_text(table, "Tabla", max_tokens=150)
    assert len(chunks) > 1
    assert all(estimate_tokens(c.text) <= 160 for c in chunks)


def test_los_titulos_dentro_de_bloques_de_codigo_no_cuentan():
    text = "## Real\n\n```bash\n# esto es un comentario, no un título\nls\n```"
    chunks = chunk_text(text, "Doc")
    assert [c.section for c in chunks] == ["Real"]


def test_texto_vacio_no_genera_fragmentos():
    assert chunk_text("   \n\n  ", "Vacío") == []
