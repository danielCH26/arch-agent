# ADR-005: Engram como MCP de memoria

**Fecha:** 2026-08-23
**Estado:** Aceptado
**Decisor:** Daniel
**Issue:** #2

## Contexto

El sistema necesita persistencia de memoria entre sesiones para:

1. Cumplir KR4 de Laura: "100% de las sesiones retomadas recuperan la etapa activa"
2. Recordar decisiones arquitectónicas del usuario
3. Aprender convenciones del equipo
4. Tracking de discoveries y bugs

## Opciones consideradas

| Opción | Pros | Contras |
|--------|------|---------|
| **Engram** | 19 tools, local, single binary, FTS5 | Nuevo pero activo |
| Redis (memoria) | Rápido | Sin estructura semántica |
| SQLite propio | Simple | Reinventar la rueda |
| PostgreSQL (más tablas) | Ya lo tenemos | Poluir la DB de negocio |
| claude-mem | Open source | Múltiples runtimes (Node + Bun + Python) |

## Decisión

**Elegido: Engram como MCP**

Razones:
1. **Cero dependencias runtime** — un solo binario Go
2. **SQLite + FTS5 embebido** — búsqueda full-text nativa
3. **19 tools especializados** para gestión de memoria
4. **Soporte MCP nativo** — se integra con nuestro agente LangChain
5. **Imagen Docker oficial** `ghcr.io/gentleman-programming/engram:latest`

## Consecuencias

### Positivas
- Cumple el KR4 de Laura sin código custom
- Persistencia cross-session automática
- Búsqueda semántica + full-text en memorias
- Compatible con el principio "local-first" del proyecto

### Negativas
- Dependencia externa (proyecto nuevo)
- Volumen Docker adicional para persistir SQLite

## Uso

```python
# En el agente LangChain
mcp_config = {
    "engram": {
        "transport": "stdio",
        "command": "engram",
        "args": ["mcp", "--project", "asistente-arquitectura"],
    },
}
```

## Referencias

- [Engram GitHub](https://github.com/Gentleman-Programming/engram)
- Imagen: `ghcr.io/gentleman-programming/engram:latest`
