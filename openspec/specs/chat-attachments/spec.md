# Chat Attachments — Specification

**Capability folder:** `openspec/specs/chat-attachments/`
**Branch:** `feature/F13-puppeteer-mcp` @ `4c5a9d3`
**Issue:** [#17](https://github.com/danielCH26/arch-agent/issues/17)

## Scope Confirmation

**F13 ships Mermaid-only rendering. Arbitrary HTML rendering (including any sanitizer) is OUT of scope for F13; revisit as F14.** This spec defines persistence + serving for rendered screenshots; it does not describe any HTML rendering flow.

## Purpose

Persist and serve chat-rendered screenshot attachments atomically with the assistant message row. `GET /api/chat/attachments/{id}` is gated by a signed query-string token (TTL ≤ 5 min) so `<img src>` can load the file without an `Authorization` header. Cross-user or unknown ids return 404 (NOT 403) to avoid existence leaks.

## Requirements

| ID | Requirement |
|---|---|
| REQ-ATT-1 | `_persist_turn` SHALL insert the assistant `messages` row AND every attachment row in the SAME Postgres transaction (extends F12 REQ-4). If either insert fails, BOTH roll back AND SSE emits `event: error`. |
| REQ-ATT-2 | `GET /api/chat/attachments/{id}` SHALL require a signed query-string token (TTL ≤ 5 min). The route SHALL return 200 + file bytes when the token is valid AND the attachment is owned by the current user; 404 when the attachment is cross-user or unknown; 401 when the token is missing, forged, or expired. |
| REQ-ATT-3 | The endpoint SHALL set `Content-Type` from the stored row, `Content-Length` from the file, AND `Content-Disposition: inline; filename="<attachment.filename>"`. |

## Scenarios

| ID | GIVEN / WHEN / THEN |
|---|---|
| SCN-ATT-1 | Agent emits a Mermaid block; `_persist_turn` runs. THEN the assistant message row AND the attachment row land in ONE transaction; a simulated failure on either insert rolls back BOTH rows AND SSE emits `event: error` (mirrors F12 SCN-7). |
| SCN-ATT-2 | Attachment row insert succeeds but the assistant message insert fails; `_persist_turn` rolls back. THEN a subsequent `list_attachments(message_id=…)` returns `[]`. |
| SCN-ATT-3 | Valid token AND attachment owned by the current user. THEN `GET /api/chat/attachments/{id}?token=…` returns 200 + `Content-Type: image/png` + the file bytes. |
| SCN-ATT-4 | Valid token BUT attachment owned by a different user. THEN the route returns 404 (NOT 403 — avoid existence leak). |
| SCN-ATT-5 | Token missing, signed with a wrong secret, OR older than 5 min. THEN the route returns 401. |
| SCN-ATT-6 | Attachment filename is `diagram-12345.png`. THEN the response carries `Content-Disposition: inline; filename="diagram-12345.png"`. |

## Out of Scope

- Authenticated client-side fetch with custom `Authorization` headers (the `<img>` element cannot send them).
- Non-PNG binary payloads (PDF, SVG) — `puppeteer_pdf` is not adopted in F13.
- Retention / deletion policies on attachment rows (promote JSONB → normalized table when those land — see ADR-013 §Storage).

## Risks

- Cross-user attachment leak → REQ-ATT-2 404 on miss + signed-token TTL + per-token secret rotation.
- Browser cache replay after token expiry → REQ-ATT-2 re-validates the token on every request; client cache TTL is short.

## References

- `openspec/changes/2026-09-07-F13-puppeteer-mcp/{explore,proposal}.md`
- `openspec/specs/puppeteer-mcp-integration/spec.md` — REQ-PMCP-1 emits the event REQ-ATT-1 stores.
- `openspec/specs/engram-conversation-memory/spec.md` REQ-4 — pre-`done` transaction seam extended here.
