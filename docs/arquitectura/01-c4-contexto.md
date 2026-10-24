# C4 · Nivel 1: Contexto

**Pregunta que responde:** ¿quién usa JARVIS y con qué sistemas externos se relaciona?

El modelo C4 describe un sistema en 4 niveles de zoom: **Contexto → Contenedores → Componentes → Código**.
Éste es el nivel más alejado: JARVIS se ve como una sola caja.

```mermaid
C4Context
  title Diagrama de contexto · JARVIS v1.0

  Person(owner, "Dueño", "Tú. Conversa, carga conocimiento y entrena a JARVIS.")
  Person(family, "Familia e invitados", "Conversan desde sus dispositivos en la red de la casa.")

  System(jarvis, "JARVIS", "Asistente personal con IA, 100 % local. Entiende y responde por texto y por voz.")

  System_Ext(web, "Fuentes públicas de conocimiento", "Wikipedia, documentación técnica, sitios web. Sólo durante el desarrollo.")
  System_Ext(colab, "Google Colab o Kaggle", "GPU gratuita para entrenar el adaptador LoRA con datos públicos.")
  System_Ext(github, "GitHub", "Código y documentación. Nunca datos personales ni modelos.")

  Rel(owner, jarvis, "Habla y escribe", "HTTPS, red local")
  Rel(family, jarvis, "Habla y escribe", "HTTPS, red local")
  Rel(jarvis, web, "Descarga e indexa", "HTTPS, sólo en desarrollo")
  Rel(owner, colab, "Entrena LoRA", "Notebook")
  Rel(owner, github, "Publica el código", "git push")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Elementos

| Elemento | Tipo | Descripción |
|---|---|---|
| Dueño | Persona | Rol `owner`. Único que puede cargar conocimiento, entrenar y administrar modelos y usuarios. |
| Familia e invitados | Persona | Roles `member` y `guest`. Conversan, sin acceso a los datos personales del dueño. |
| **JARVIS** | Sistema | Todo lo que corre en el PC servidor: app web, API, modelos, base de datos y voz. |
| Fuentes públicas | Sistema externo | Sólo se consultan **durante el desarrollo**, para construir la base de conocimiento. Luego se puede desconectar. |
| Colab o Kaggle | Sistema externo | Entrena con **datos públicos**. Los datos personales nunca se suben. |
| GitHub | Sistema externo | Escaparate del proyecto. El `.gitignore` impide subir datos, modelos y secretos. |

## Límites de privacidad

- Ninguna conversación sale del PC.
- No hay APIs de terceros para el modelo de lenguaje, la voz ni los embeddings.
- La única conexión saliente de JARVIS (descargar fuentes públicas) se puede desactivar con `INGESTION_ALLOW_INTERNET=false`.
