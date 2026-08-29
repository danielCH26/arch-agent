# ADR-006: Chainlit como UI conversacional

**Fecha:** 2026-08-23
**Estado:** Aceptado
**Decisor:** Daniel + Sofía
**Issue:** #2

## Contexto

Necesitamos una interfaz de usuario que:

1. Sea conversacional (chat con el agente)
2. Soporte renderizado de Markdown + imágenes
3. Permita aprobar/rechazar/modificar propuestas
4. Sea rápida de implementar (Sprint 1)
5. Funcione bien con LangChain

## Opciones consideradas

| Opción | Pros | Contras |
|--------|------|---------|
| **Chainlit** | Hecho para LLM apps, Markdown nativo, MCP support | Menos personalizable que React |
| Streamlit | Fácil de usar | Menos orientado a chat |
| FastAPI + React/HTMX | Máximo control | Más trabajo de frontend |
| Gradio | Similar a Streamlit | Menos flexible |
| Custom HTML/JS | Cero dependencias | Mucho trabajo |

## Decisión

**Elegido: Chainlit**

Razones:
1. **Hecho para apps de LLM** — chat, streaming, async
2. **Markdown nativo** — las propuestas se ven bien out-of-the-box
3. **Integración LangChain** vía callbacks
4. **MCP support** oficial
5. **Sofía (UI/Frontend)** puede enfocarse en la experiencia, no en plumbing

## Componentes UI clave

| Componente | Para qué |
|-----------|----------|
| Chat message | Interacción usuario-agente |
| AskUserMessage | Aprobación Aprueba/Modifica/Rechaza |
| Image | Diagramas Mermaid renderizados |
| File upload | HU13 (subir PDF/MD) |
| Sidebar | Lista de proyectos (HU3) |

## Consecuencias

### Positivas
- Velocidad de desarrollo (MVP en pocas horas)
- UI profesional out-of-the-box
- Streaming de respuestas nativo

### Negativas
- Menos personalizable que React puro
- Sofia tiene menos espacio para UI custom

## Plan de migración (futuro)

Si necesitamos UI más rica en producción:
- Chainlit sigue siendo viable (soporta custom HTML/JS)
- O migrar a FastAPI + frontend separado

## Referencias

- [Chainlit Docs](https://docs.chainlit.io)
- [Chainlit + LangChain](https://docs.chainlit.io/integrations/langchain)
