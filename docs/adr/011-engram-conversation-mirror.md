# ADR-011: Engram como espejo del historial de conversacion

**Fecha:** 2026-09-06
**Estado:** Aceptado (propuesto con F12)
**Decisor:** Daniel
**Issue:** #14
**Proposal:** `openspec/changes/F12-engram-mcp/proposal.md`

## Contexto

Issue #14 pide dos memorias distintas:

1. **Decisiones arquitectonicas y contexto del proyecto** (team-facing) — ADR-005 ya eligio Engram como substrate.
2. **Historial de chat del usuario** (user-facing) — al recargar la pagina, el usuario debe seguir desde donde dejo.

Hoy:

- `app/api/chat.py:155-188` cierra el SSE stream sin persistir nada.
- `frontend/src/stores/chatStore.ts:29` arranca `messages=[]` en cada reload.
- `app/core/engram_client.py` (65 LoC) solo escribe (`create_session`, `end_session`, `save_observation`, `get_context`) — el HTTP v2.0.0-rc.6 NO expone `GET /observations` ni `GET /sessions/{id}/messages` (verificado en explore.md §2.2 con 16 probes).
- `app/models/session.py` tiene `engram_state JSON` pero `save_session_state`/`load_session_state` no tienen callers en el codigo.

F12 necesita decidir donde vive el historial de chat y como se sincroniza con Engram.

## Opciones consideradas

| Opcion | Pros | Contras |
|--------|------|---------|
| **A. Postgres unico** (nueva tabla `messages`, sin Engram para chat) | Simple, ACID, queryable, sin acoplamiento a Engram | Viola el espiritu de ADR-005 ("memory lives in Engram"); pierde recall semantico cross-session para chat |
| **B. Engram unico** (cada mensaje es observation, read via MCP stdio) | Uniforme con memoria de decisiones; preserva ADR-005 | HTTP v2 no lista-by-session; requiere fork de Engram o adoptar MCP-stdio en backend (≥300 LoC + nueva dep) |
| **C. Hybrid** (Postgres = verdad, Engram = espejo fire-and-forget) | Separacion limpia hot/warm; chat UI nunca bloquea por Engram; mantiene a Engram como cerebro semantico; rollback trivial | Dual-write (mitigado con try/except + fire-and-forget) |

## Decision

**Elegido: C — Hybrid con Postgres como source of truth y Engram como espejo semantico fire-and-forget**

Postgres `messages` es la fuente canonica del historial de chat. Engram recibe una copia paralela via `engram_client.save_observation(...)` con `engram_observation_id` almacenado de vuelta en la fila de Postgres para trazabilidad inversa. El mirror es **fire-and-forget** dentro de un `try/except EngramError: log` — si Engram cae, el chat sigue funcionando y la historia se persiste en Postgres.

Recuperacion del historial: `SELECT ... FROM messages WHERE user_id=? AND project_id=? ORDER BY created_at DESC LIMIT N` (default N=5 turns; `?limit=` override). Engram `get_context(project)` queda disponible para recall explicito de largo alcance, pero **no** se inyecta automaticamente en el prompt (control de costo de tokens; ver F12 proposal §6 row 7).

session_id de Engram: scope **per-(user, project)** con clave deterministica `arch-agent-user-{user_id}-project-{project_id}-chat` (alineado con `app/__init__.py:33-36` `get_engram_project_key(user_id)` y la estructura project-scoped del chat).

## Consecuencias

### Positivas

- Cumple los dos ACs de issue #14 simultaneamente: persistencia del historial de chat (Postgres) + memoria semantica cross-session (Engram).
- Chat UI nunca se bloquea por Engram — degrada silenciosamente.
- Postgres queda preparado para FTS futuro (`tsvector` sobre `content`) sin coupling con Engram.
- Migracion nueva (`0008_add_messages_table.sql`) es idempotente y reversible.

### Negativas

- Dual-write — si Engram esta caido durante minutos, las observaciones se pierden (no son criticas; Postgres es la verdad).
- `session_store.py` queda como codigo muerto (no se refactorea en F12; documentado como deuda).
- Tests `tests/test_llm_validator.py:170,178,197,223` requieren actualizacion de mocks cuando se agreguen los 4 metodos faltantes a `EngramClient`.

## Uso

```python
# app/core/message_store.py (F12.1)
from app.core.engram_client import EngramClient
from app.models.message import Message

def insert_message(db, *, user_id, project_id, role, content, sources_json=None) -> Message:
    msg = Message(user_id=user_id, project_id=project_id, role=role,
                  content=content, sources_json=sources_json or {})
    db.add(msg); db.commit(); db.refresh(msg)
    # Fire-and-forget Engram mirror -- best effort, never raises.
    try:
        engram = get_engram_client()
        engram.create_session(
            session_id=f"arch-agent-user-{user_id}-project-{project_id}-chat",
            project=get_engram_project_key(user_id),
            directory=".",
        )
        engram.save_observation(
            session_id=f"arch-agent-user-{user_id}-project-{project_id}-chat",
            project=get_engram_project_key(user_id),
            title=f"msg-{msg.id}",
            content=content,
            observation_type="chat_message",
        )
        msg.engram_observation_id = <returned id>  # reverse link
        db.commit()
    except EngramError as exc:
        logger.warning("Engram mirror skipped for message %s: %s", msg.id, exc)
    return msg
```

## Referencias

- ADR-002 — PostgreSQL + PGVector como DB unica (la tabla `messages` vive en la misma instancia).
- ADR-005 — Engram como MCP de memoria (alcance: decisiones + contexto; este ADR extiende al historial de chat).
- `openspec/changes/F12-engram-mcp/explore.md` — endpoint probes + alternativas A/B/C.
- `openspec/changes/F12-engram-mcp/proposal.md` §6 — decision table con las 8 ambiguedades resueltas.
- Issue #14 — https://github.com/danielCH26/arch-agent/issues/14
- Migration pattern: `migrations/0003_sync_sessions_table.sql` (idempotent ALTER).
