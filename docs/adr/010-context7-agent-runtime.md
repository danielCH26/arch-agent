# ADR-010: Context7 transport selection & agent runtime shape

**Fecha:** 2026-09-05
**Estado:** Aceptado (pendiente de merge vía F11)
**Decisor:** Daniel
**Issue:** #13 ([F11] Context7 MCP integrado)
**Supersede:** ninguno
**Relacionado:** ADR-001 (LangChain), ADR-004 (Langfuse), ADR-005 (Engram MCP), ADR-007 (six MCPs)

## Contexto

F11 introduce Context7 MCP en el agente de chat. A la fecha del HEAD `d139c9e` el repositorio tiene:

- `app/api/chat.py` que llama `model.astream(prompt)` directamente — **no existe un agente LangChain**.
- Cero código de Langfuse en `app/` (solo `SSEStreamCallbackHandler` para tokens).
- Cero dependencias MCP (`mcp`, `langchain-mcp-adapters`, `langgraph` no están en `requirements.txt`).
- ADR-007 que prescribe `transport: http` a `https://mcp.context7.com/mcp` pero nunca se implementó.
- ADR-004 que acepta Langfuse pero el wiring nunca aterrizó en código.

F11 debe tomar decisiones ejecutables en cuatro frentes: (a) transporte de Context7, (b) forma del runtime del agente, (c) alcance del wiring de Langfuse, (d) ubicación del wrapper MCP.

## Opciones consideradas

### A.1 — Transporte de Context7

| Opción | Pros | Contras |
|---|---|---|
| **A.1.a — HTTPS público a `mcp.context7.com`** (recomendado) | Cero infra nueva. ADR-007 ya lo eligió. `langchain-mcp-adapters` soporta `transport: http` con headers runtime. | Dependencia de Upstash; rate limit free-tier. |
| A.1.b — Sidecar stdio local vía `npx @upstash/context7-mcp` | Sin dependencia externa; latencia predecible en red Docker local. | Agrega imagen Node al stack (hoy cero Node); cold start por `npx`; supply-chain risk npm; contradice ADR-007. |

### A.2 — Runtime del agente

| Opción | Pros | Contras |
|---|---|---|
| **`langchain.agents.create_agent`** (recomendado) | API moderna oficial; ~50 LoC menos que StateGraph; `callbacks=` nativo para Langfuse + SSE. | Menos explícito que StateGraph; más difícil agregar nodos custom. |
| `langgraph.graph.StateGraph` + `ToolNode` + `tools_condition` | Más explícito; encaja con futuros MCPs múltiples. | Más boilerplate; sobreingeniería para 1 MCP. |
| Continuar `model.astream(prompt)` con RAG en el prompt | Cero cambio. | El AC de Context7 requiere tool-use loop; imposible sin agente. |

### A.3 — Alcance del wiring de Langfuse

| Opción | Pros | Contras |
|---|---|---|
| **Inline en F11** (recomendado, decisión de usuario) | Cumple los 3 ACs del issue #13 en un solo cambio; sin "F11 incompleto". | Incrementa scope de F11. |
| Split en F12 "Langfuse observability" | F11 más pequeño. | F11 queda con AC3 incumplido → no se puede archivar; retrasa la demo. |

### A.4 — Ubicación del wrapper MCP

| Opción | Pros | Contras |
|---|---|---|
| **`app/core/context7_mcp.py`** con `MultiServerMCPClient` singleton (recomendado) | Paralelo a `app/core/engram_client.py`; mismo namespace; fácil mockear. | Wrapper fino para un solo servidor. |
| `app/mcp/context7.py` (nuevo namespace) | Prepara el terreno para los 6 MCPs de ADR-007. | Carpeta vacía hasta que lleguen los otros 5 MCPs. |
| Sin wrapper, inline en `app/core/agent.py` | Menos archivos. | Imposible testear isolated; mezcla concerns. |

## Decisión

**A.1.a + A.2.create_agent + A.3.inline + A.4.context7_mcp.py.**

Resumen ejecutable:

1. **Transporte:** `transport: "http"` (también aceptable `"streamable_http"`), URL `https://mcp.context7.com/mcp`, header `Authorization: Bearer ${CONTEXT7_API_KEY}` solo cuando la variable esté no-vacía. Re-afirma ADR-007 línea 76.
2. **Runtime:** `langchain.agents.create_agent(model, tools, system_prompt, ...)` con `langchain>=0.3,<0.4` pinneado. StateGraph queda reservado para un futuro cambio multi-MCP.
3. **Langfuse:** wireado inline en F11 vía `app/core/langfuse_tracer.py` que expone `get_langfuse_handler() -> CallbackHandler | None`. Si las env vars faltan, retorna `None` y el agente corre sin tracing (logged WARNING).
4. **Wrapper:** `app/core/context7_mcp.py` con `MultiServerMCPClient` singleton + helper async `get_context7_tools() -> list[BaseTool]`. El singleton se inicializa lazy en el primer request para no bloquear el startup del backend.

### Configuración efectiva

```python
# app/core/context7_mcp.py
from langchain_mcp_adapters.client import MultiServerMCPClient
import os

_CLIENT: MultiServerMCPClient | None = None

def _build() -> MultiServerMCPClient:
    api_key = os.getenv("CONTEXT7_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return MultiServerMCPClient({
        "context7": {
            "transport": "http",
            "url": "https://mcp.context7.com/mcp",
            "headers": headers,
        }
    })

async def get_context7_tools() -> list[BaseTool]:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = _build()
    return await _CLIENT.get_tools()
```

```python
# app/core/agent.py (sketch)
from langchain.agents import create_agent
from langchain_core.runnables import ConfigurableFieldSpec

async def run_agent(model, system_prompt: str, user_message: str, *, callbacks: list):
    tools = await get_context7_tools()
    agent = create_agent(model, tools, system_prompt=system_prompt)
    config = {"callbacks": callbacks}
    async for event in agent.astream_events({"messages": [{"role": "user", "content": user_message}]}, config=config, version="v2"):
        yield event
```

```python
# app/core/langfuse_tracer.py (sketch)
from langfuse.langchain import CallbackHandler

def get_langfuse_handler() -> CallbackHandler | None:
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    sk = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    if not pk or not sk:
        logger.warning("Langfuse env vars missing; agent will run without tracing.")
        return None
    return CallbackHandler()
```

### Precedencia RAG ↔ Context7

- RAG (`app/core/rag.py::similarity_search`, scope `patterns` + `all`) corre siempre y su resultado se inyecta en el system prompt.
- Context7 corre on-demand como tool; el system prompt sugiere al agente llamar `resolve-library-id` solo cuando el usuario nombra una librería externa.
- Context7 result se trunca a 4000 caracteres antes de inyectarse.
- Modelo decide cuál usar; no hay pre-decisión rígida.

## Consecuencias

### Positivas
- Cierra los 3 ACs del issue #13 en un solo cambio.
- ADR-007 y ADR-001 finalmente tienen una implementación concreta (primer MCP y primer agente del repo).
- `MultiServerMCPClient` queda extensible para los otros 5 MCPs (Filesystem, Puppeteer, Web Search, Fetch) sin refactor.
- Langfuse cumple OKR 4 - KR1 de Santiago: "100% de las ejecuciones registradas en trazas".
- No se agregan servicios Docker; el stack queda en 11 servicios.

### Negativas
- F11 deja de ser "solo Context7" — incluye el agente completo y Langfuse. Mitigado por la decisión de usuario (atomic) y por el chained-PR plan en `proposal.md §12`.
- `requirements.txt` crece en 3 dependencias (`langchain-mcp-adapters`, `mcp`, `langfuse`). Mitigado por pin exacto y pure-Python wheels.
- Si `langchain.agents.create_agent` cambia entre minor versions, requerirá bump manual. Mitigado por `langchain>=0.3,<0.4`.

## Mitigación de riesgo

| Riesgo | Mitigación |
|---|---|
| Cambio de API en `langchain` | Pin `>=0.3,<0.4` en `requirements.txt`. |
| Context7 rename de tools | Pin adapter `==0.3.2`; test asserting `resolve-library-id` y `query-docs` por nombre exacto. |
| Context7 429 / outage | Timeout 5s; emitir `event: degraded`; continuar con RAG. |
| Langfuse env unset | `get_langfuse_handler()` retorna `None`; WARNING logged; agente sigue. |
| Egress bloqueado en CI/demo | `@pytest.mark.skipif(not CONTEXT7_API_KEY)`; recorded-fixture test para CI offline. |

## Tabla fallback

- Si Context7 falla: agente continúa con RAG only (success criteria §9 del proposal).
- Si Langfuse falla: catch en `get_langfuse_handler()` retorna `None`; el agente sigue; se loggea WARNING.
- Si `MultiServerMCPClient.get_tools()` falla al startup: el helper retorna `[]` y el agente arranca sin tools (logged ERROR una sola vez).

## Referencias

- Issue #13 — https://github.com/danielCH26/arch-agent/issues/13
- ADR-001 (LangChain framework), ADR-004 (Langfuse), ADR-005 (Engram MCP), ADR-007 (six MCPs)
- `openspec/changes/F11-context7-mcp/explore.md`
- `openspec/changes/F11-context7-mcp/proposal.md`
- https://github.com/upstash/context7
- https://pypi.org/project/langchain-mcp-adapters/ (0.3.2)
- https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http
