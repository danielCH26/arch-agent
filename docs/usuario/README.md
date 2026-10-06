# Documentación de usuario — Arch Agent

Esta carpeta reúne la documentación pensada para **quien usa Arch Agent** (no para quien lo desarrolla). Si buscas cómo levantar el stack o contribuir al código, mira el [README principal](../../README.md) y [ARCHITECTURE.md](../ARCHITECTURE.md).

Arch Agent es un asistente con IA que te acompaña desde la idea de un producto hasta una **propuesta de arquitectura justificada**, con diagramas y trade-offs, en cuatro fases:

```
Requerimientos  →  Propuesta  →  Refinamiento  →  Revisión
 (elicitación)    (arquitectura)   (diagrama)
```

#Screenshot-página-principal
<!-- Reemplazar por: ![Página principal de Arch Agent](screenshots/pagina-principal.png) -->

## Contenido

| Documento | Para qué sirve |
|-----------|----------------|
| [Guía de inicio rápido](01-inicio-rapido.md) | De cero a tu primera propuesta en ~10 minutos. |
| [Tutorial paso a paso](02-tutorial.md) | Recorrido completo por cada pantalla y cada fase, con un proyecto de ejemplo. |
| [Preguntas frecuentes (FAQ)](03-faq.md) | Problemas habituales y cómo resolverlos. |
| [Glosario de términos](04-glosario.md) | Qué significa cada concepto que aparece en la app. |
| [Capturas de pantalla](screenshots/README.md) | Listado de las capturas usadas en esta documentación. |

## Requisitos para el usuario

- Un navegador moderno (Chrome, Edge, Firefox o Safari actualizados).
- Acceso a la URL de Arch Agent (en una instalación local: **http://localhost:5173**).
- Un proveedor de LLM compatible con la API de OpenAI (OpenAI, Ollama, LM Studio, OpenRouter, Groq, etc.) y, si el proveedor lo exige, su **API key**.