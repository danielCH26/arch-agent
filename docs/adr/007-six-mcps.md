# ADR-007: Selección de 6 MCPs para el MVP

**Fecha:** 2026-08-23
**Estado:** Aceptado
**Decisor:** Daniel
**Issue:** #2

## Contexto

El agente necesita herramientas externas (MCPs) para:

1. Buscar documentación técnica actualizada
2. Recordar contexto entre sesiones
3. Renderizar diagramas
4. Leer código del usuario
5. Buscar en internet
6. Traer contenido de URLs específicas

## MCPs evaluados

| MCP | Función | Tier | Decisión |
|-----|---------|------|----------|
| **Context7** | Docs técnicas actualizadas | 1 (crítico) | ✅ Incluido |
| **Engram** | Memoria persistente | 1 (crítico) | ✅ Incluido |
| **Puppeteer** | Render Mermaid a PNG | 1 (crítico) | ✅ Incluido |
| **Filesystem** | Leer proyecto del usuario | 2 (recomendable) | ✅ Incluido |
| **Web Search** | Búsqueda general internet | 2 (recomendable) | ✅ Incluido |
| **Fetch** | Traer contenido de URL | 2 (recomendable) | ✅ Incluido |
| CodeGraph | Análisis estático de código | 3 | ❌ Overkill para MVP |
| Git | Repo Git específico | 3 | ❌ Filesystem lo cubre |

## Decisión

**Elegidos: 6 MCPs (Context7, Engram, Puppeteer, Filesystem, Web Search, Fetch)**

Razones por tier:

### Tier 1 — Críticos (sin estos el sistema no funciona)
- **Context7**: el agente necesita docs actualizadas de librerías
- **Engram**: sin memoria, el sistema no cumple KR4 de Laura
- **Puppeteer**: para visualizar diagramas Mermaid

### Tier 2 — Recomendables (mejoran significativamente)
- **Filesystem**: para analizar proyectos existentes del usuario
- **Web Search**: tendencias y comparativas actualizadas
- **Fetch**: traer contenido de URLs específicas que el usuario pasa

### Por qué NO CodeGraph ni Git
- **CodeGraph**: requiere indexación, overkill para MVP
- **Git**: Filesystem MCP es más general y cubre el caso

## Consecuencias

### Positivas
- 6 MCPs dan al agente capacidades amplias sin ser excesivo
- Filesystem cubre el caso de Git + CodeGraph
- Web Search + Fetch se complementan (buscar vs traer)

### Negativas
- Más MCPs = más superficie de falla
- Cada MCP tiene su propia curva de aprendizaje

## Mitigación de riesgo

| Riesgo | Mitigación |
|--------|------------|
| MCP no responde | Try/catch en cada tool call |
| Rate limit (Web Search) | Caché + retry con backoff |
| Filesystem expone datos sensibles | Solo accede a `/app/uploads` |
| Fetch a URL muerta | Timeout 10s |

## Implementación

```python
mcp_config = {
    "context7": {"transport": "http", "url": "https://mcp.context7.com/mcp"},
    "engram": {"transport": "stdio", "command": "engram", "args": ["mcp"]},
    "puppeteer": {"transport": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-puppeteer"]},
    "filesystem": {"transport": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/app/uploads"]},
    "websearch": {"transport": "http", "url": "${WEB_SEARCH_URL}"},
    "fetch": {"transport": "stdio", "command": "uvx", "args": ["mcp-server-fetch"]},
}
```

## Referencias

- [Model Context Protocol](https://modelcontextprotocol.io)
- Análisis completo en `STACK_TECNOLOGICO.md` sección 19
