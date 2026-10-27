---
name: adr-design
description: Identidad visual ("ArchAgent Blueprint") y contrato de contenido del ADR que genera ArchAgent. Úsala antes de tocar el armado del ADR (app/core/adr_generator.py), su PDF (frontend/src/components/adrPrint.ts), los colores de los diagramas o la verificación previa a la entrega.
---

# Diseño del ADR

El ADR es el entregable del proyecto: lo recibe la empresa o el cliente. Tiene
que verse profesional, con identidad propia, y cada sección tiene que aportar
algo de ESE proyecto.

## 1. Identidad visual

Fuente de verdad, duplicada a propósito (el frontend se construye aparte):

| Dónde | Qué usa |
| --- | --- |
| `app/core/adr_theme.py` | `ADR_PALETTE`, `ADR_FONTS`, tema Mermaid (`mermaid_theme_config`, `themed_mermaid`) |
| `frontend/src/components/adrTheme.ts` | `ADR_PALETTE`, `ADR_FONTS`, `ADR_SPACE`, `ADR_TYPE` para el PDF |

`tests/core/test_adr_quality.py::test_la_paleta_del_pdf_es_la_misma_que_la_de_los_diagramas`
falla si las dos paletas se separan. Cambia siempre las dos.

### Paleta

| Token | Valor | Uso |
| --- | --- | --- |
| `navy` | `#0B1F3A` | Banda de portada, encabezado de tablas, títulos de capítulo |
| `primary` | `#1D4E89` | Títulos de subsección, enlaces, filete izquierdo de capítulos, flechas de diagramas |
| `secondary` | `#2F74D0` | Viñetas, bordes de nodos, filete de citas y código |
| `accent` | `#38A3D9` | Solo detalles: filete bajo la portada, "Agent" de la marca, eyebrow |
| `sky` | `#D6E6F8` | Bordes suaves, nodos secundarios, fondo de pantalla de la vista de impresión |
| `tint` | `#EEF4FC` | Fondos de recuadros (resumen ejecutivo, citas) y de nodos |
| `ink` / `muted` | `#1B2533` / `#5B6B80` | Texto / texto secundario y pies de figura |
| `line` / `paper` | `#D9E2EC` / `#F7F9FC` | Bordes de tabla / filas alternas y bloques de código |
| `success*`, `warning*`, `danger*` | verde, ámbar, rojo | SOLO estados (Aceptado, Propuesto, avisos). Nunca decorativos |

Reglas: el azul estructura (títulos, tablas, filetes); el texto corrido va en
`ink`. No introducir otros tonos (nada de índigo, violeta ni grises de Tailwind).

### Tipografía y espaciado

- Títulos: **Plus Jakarta Sans** (la misma marca de la app), 700–800.
- Cuerpo: **Inter** 10.5 pt, interlineado 1.6. Código: **JetBrains Mono** 8.5 pt.
- Todas con respaldo del sistema (`Segoe UI`, Helvetica, Arial / Consolas): el
  PDF tiene que salir bien sin conexión.
- Escala de espaciado `ADR_SPACE` (4, 8, 12, 18, 28 pt). No usar valores sueltos.

### Componentes del PDF

- **Portada**: banda `navy` a sangre con la marca, `ADR-001`, título, subtítulo
  y estado (insignia verde si está aceptado, ámbar si no); debajo la ficha
  (fecha, propuesta aprobada, generado por) y la decisión en una línea.
- **Capítulos** (`##`): filete izquierdo `primary` de 5 pt; los grandes
  empiezan en página nueva (`PAGE_BREAK_BEFORE`).
- **Tablas**: encabezado `navy` con texto blanco, filas alternas `paper`,
  bordes `line`, esquinas redondeadas.
- **Resumen ejecutivo**: recuadro `tint` con filete superior `primary`.
- **Avisos de la revisión automática**: recuadro ámbar (`warning`).
- **Diagramas**: figura con borde `sky`; el pie es el del propio ADR
  ("_Figura n. ..._"), que la vista de impresión mueve a `<figcaption>`.

## 2. Diagramas

- Todos los diagramas usan el tema `base` de Mermaid con la paleta
  (`mermaid_theme_config`): la captura que hace Puppeteer
  (`agent._build_mermaid_preview_html`) y el bloque del `.md` (con la directiva
  `%%{init: ...}%%` de `themed_mermaid`, que GitHub y GitLab respetan).
- Sección 4: con un solo diagrama, `## 4. Diagrama de arquitectura`. Con el de
  despliegue (`AdrContext.deployment_mermaid`), `## 4. Diagramas` con
  `### 4.1 Arquitectura` y `### 4.2 Despliegue`. Cada uno con su pie
  `_Figura n. <qué muestra>._`
- Para sumar otro diagrama: agrégalo a `_diagrams_block` con título y pie, y en
  `AdrPanel.tsx` asígnale su imagen por posición (`splitMermaidBlocks`).

## 3. Contrato de contenido (qué aporta cada sección)

| Sección | Aporta | Fuente |
| --- | --- | --- |
| Ficha | Estado, fecha, aprobación, iteración aprobada | Datos |
| Resumen ejecutivo | Problema, para quién, decisión, recursos, 3 riesgos, qué falta decidir | Datos + 7.4/7.8 |
| 1. Contexto | Problema, usuarios, descripción inicial (si difiere) | Elicitación |
| 2. Requerimientos | Funcionalidades, restricciones, calidad, escala, contexto técnico, datos de viabilidad | Elicitación |
| 3. Decisión | La decisión en una línea + la propuesta aprobada con trade-offs y ajustes pedidos | Propuesta |
| 4. Diagramas | Arquitectura (y despliegue) con el tema del ADR | Refinamiento |
| 5. Referencias | Patrones usados y sus fuentes curadas | Catálogo |
| 6. Historial | Decisiones por fase con comentarios y cambios de la revisión | `approvals` |
| 7. Guía | 7.1 componentes … 7.8 preguntas abiertas | LLM + revisión |
| Anexo A | Preguntas y respuestas literales de la elicitación | Elicitación |

Se quitó (no aportaba o repetía): la fila "Proyecto" (ya es el título), "Fase
actual" (siempre Revisión), el párrafo introductorio y el del resumen ejecutivo
(iguales en todos los ADR), la frase fija de la sección 3 y el "(similitud 87%)"
de las referencias (medida interna).

No agregues secciones fijas ni textos que se repitan en todos los ADR: si una
frase serviría igual para cualquier proyecto, sobra.

## 4. Verificación previa a la entrega

`verify_adr(ctx, markdown, guide)` (en `adr_generator.py`, con las primitivas de
`app/core/adr_quality.py`) corre al generar y al aprobar; el resultado viaja
como `quality_issues` y el panel lo muestra antes de aprobar. Revisa:

- secciones vacías o con solo un marcador (`_No especificado._`);
- datos que no pueden faltar: funcionalidades, restricciones, atributos de
  calidad, presupuesto/equipo/plazo y el diagrama;
- la guía 7.1–7.8: muy corta (< 60 caracteres), genérica (menos de 2 términos
  propios del proyecto: funcionalidades, tecnologías, nombres del diagrama,
  restricciones) o con frases de relleno (`FILLER_PHRASES`).

Los avisos de la guía también entran a la pasada de corrección del LLM
(`review_guide` → `repair_llm_sections`).

Si una palabra genérica hace pasar secciones vacías de contenido, agrégala a
`GENERIC_WORDS`; si una frase de relleno se cuela, a `FILLER_PHRASES`. Prueba
siempre contra los casos golden (`data/golden`).
