# arch-agent

Asistente que guía a equipos de desarrollo en la definición de arquitecturas de software.

## Requisitos previos

- Docker Desktop en ejecución.
- Un archivo `.env` configurado.

  Sin este paso, los comandos de las siguientes secciones (Docker, PostgreSQL) fallarán o usarán valores por defecto incorrectos.

## Iniciar el entorno

Desde la raíz del proyecto, con el `.env` ya creado:

```bash
docker compose up -d
bash scripts/setup-local.sh  # opcional: genera JWT/ENCRYPTION_KEY, corre init_db + migrations
```

El script `setup-local.sh` es **opcional**. Si tu `.env` ya tiene `JWT_SECRET_KEY` y `ENCRYPTION_KEY`, podés saltarlo.

**Abrir la app:** http://localhost:5173

1. Click en **"Registrarse"** y crear un usuario (cualquier username + email + password 8+ chars con 1 mayúscula, 1 número, 1 símbolo).
2. Login automático → dashboard de proyectos.
3. **Crear un proyecto** desde el dashboard (botón "Nuevo Proyecto").
4. **Configurar el LLM** desde `Settings → LLM Config` (wizard de 3 pasos, ver README.md).
5. **Abrir el chat** del proyecto y empezar a chatear con el agente.

Para confirmar que los servicios requeridos están activos:

```bash
docker compose ps postgres-app engram engram-proxy backend spa
```

## Pruebas de aceptación — sesión persistente

**Historia de usuario:** Como usuario, quiero que el sistema recuerde mi sesión para continuar donde quedé sin perder progreso.

**Responsable:** Laura

**Labels:** `user-story`, `sprint-1`, `backend`

### Alcance implementado

Al terminar una conversación, la aplicación guarda la sesión del usuario en PostgreSQL. Al volver a abrir el chat, recupera el proyecto activo y la fase. La tabla usada es `sessions`.

La aplicación usa PostgreSQL como fuente de verdad para el proyecto y la fase; Engram persiste el contexto resumido de cada sesión. Si Engram no está disponible, la aplicación conserva la recuperación desde PostgreSQL y registra una advertencia sin bloquear al usuario.

**Endpoints REST relevantes** (todos requieren auth JWT):

- `GET /api/projects/{id` — devuelve el proyecto y `current_phase`
- `GET /api/projects/{id}/phase` — fase actual
- `POST /api/projects/{id}/advance` — avanza a la siguiente fase (si `phase_ready=true`)
- `POST /api/projects/{id}/mark_ready` — marca la fase como lista para avanzar
- `GET /api/auth/me` — sesión activa del usuario (fase cacheada en JWT payload)

El proyecto activo y la fase se persisten **al loguearse** (middleware JWT extrae user_id) y **al cambiar de fase** (endpoint REST que actualiza DB).

### Cambio de fase en el flow actual

En la UI, el flujo de cambio de fase es:

1. **El agente detecta que la fase está completa** → marca `phase_ready=true` automáticamente (F08, planificado).
2. **El usuario revisa** en el chat (botón "Marcar como listo" o acción explícita).
3. **Click "Avanzar"** → `POST /api/projects/{id}/advance` → DB actualiza `current_phase` y resetea `phase_ready`.
4. **Al refrescar o volver** → la SPA pide el proyecto actualizado vía `/api/projects/{id` → muestra la nueva fase.

La fase también puede avanzarse manualmente vía API (con `phase_ready=true`) para testing.

### Estado actual

> Requiere que el entorno ya esté levantado (ver sección "Iniciar el entorno" arriba).

**Implementado:**
- Tabla `sessions` en `schema.sql` con columnas `user_id`, `project_id`, `active_phase`, `engram_state`, `last_seen_at`.
- Endpoint `GET /api/projects/{id}/phase` devuelve fase actual.
- La sesión JWT incluye `user_id` y el cliente cachea `project_id` en Zustand store.
- Al volver a entrar, la SPA pide el proyecto activo al backend y muestra la fase actual.

**Pendiente:**
- Persización explícita de `engram_state` en cada mensaje (F08, fuera de alcance de HU2).
- Reanudación automática del contexto en el chat (F08, fuera de alcance).

### Crear datos de prueba (sin esperar a HU3)

Si querés probar el flow de "volver y ver el proyecto + fase" sin esperar al F08:

```bash
# 1. Consultar el id de tu usuario (el que acabás de registrar)
docker compose exec -T postgres-app psql -U asistente -d asistente_db \
  -c "SELECT id, username FROM users ORDER BY id;"

# 2. Ver tus proyectos (debería haber uno del dashboard)
docker compose exec -T postgres-app psql -U asistente -d asistente_db \
  -c "SELECT id, user_id, name, current_phase, phase_ready FROM projects ORDER BY id;"

# 3. Avanzar la fase manualmente (asume phase_ready=true; si no, primero marcala)
docker compose exec -T postgres-app psql -U asistente -d asistente_db \
  -c "UPDATE projects SET current_phase = 'propuesta', phase_ready = false WHERE id = 1;"

# 4. Refrescar la SPA — debería mostrar la nueva fase
```

## Casos de prueba

Usar el mismo usuario en todos los casos. La fase se cambia vía endpoint REST o vía UI del chat.

```bash
# Via API (requiere token)
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"tu_usuario","password":"tu_password"}' \
  | jq -r .token)

# Cambiar fase (asume que el proyecto tiene phase_ready=true)
curl -X POST http://127.0.0.1:8000/api/projects/1/advance \
  -H "Authorization: Bearer $TOKEN"
```

| ID | Criterio de aceptación | Pasos | Resultado esperado | Estado |
| --- | --- | --- | --- | --- |
| CA-01 | El sistema recupera la sesión activa al reconectar | 1. Login. 2. Crear proyecto. 3. Logout. 4. Login de nuevo con el mismo usuario. | La SPA muestra el proyecto y su fase actual. | [ ] |
| CA-02 | Estado del proyecto persistido | 1. Crear proyecto en dashboard. 2. Avanzar fase vía API. 3. Logout. 4. Login de nuevo. | El proyecto sigue ahí con la fase avanzada. | [ ] |
| CA-03 | Fase activa del flujo recuperada | 1. Cambiar fase. 2. Logout. 3. Login. | La fase mostrada al volver coincide con la última guardada. | [ ] |
| CA-04 | Sin inconsistencias al retomar | 1. Avanzar dos fases distintas. 2. Logout. 3. Login. | Se muestra únicamente la última fase guardada; no hay duplicados ni filas inconsistentes. | [ ] |
| CA-05 | Memoria persistente con Engram | 1. Cambiar fase (genera observación en Engram). 2. Logout. 3. Login. | La observación de "Estado de sesión guardado" persiste en Engram. | [ ] |

### Verificación en PostgreSQL

Ejecutar la siguiente consulta, reemplazando `tu_usuario`:

```bash
docker compose exec -T postgres-app psql -U asistente -d asistente_db \
  -c "SELECT p.id, u.username, p.name, p.current_phase, p.phase_ready, s.last_seen_at
      FROM projects p
      JOIN users u ON u.id = p.user_id
      LEFT JOIN sessions s ON s.user_id = u.id
      WHERE u.username = 'tu_usuario'
      ORDER BY p.id;"
```

Validar que:
- Haya un proyecto por usuario.
- `current_phase` y `phase_ready` reflejen lo visto en la UI.
- `last_seen_at` de `sessions` se actualice con cada request autenticado.

### Evidencia sugerida

Para cada criterio aprobado, adjuntar:
- Captura del dashboard mostrando el proyecto + fase.
- Resultado de la consulta a `projects` / `sessions`.
- Fecha, persona que ejecutó la prueba y estado final (aprobado/fallido).

## Componentes relacionados

- **Endpoints:** `app/api/projects.py`, `app/api/auth.py`
- **Modelo ORM Project:** `app/models/project.py` (columnas `current_phase`, `phase_ready`)
- **Modelo ORM Session:** `app/models/session.py`
- **Esquema PostgreSQL:** `schema.sql` (tablas `users`, `projects`, `sessions`)
- **Migraciones incrementales:** `migrations/0001_add_phase_ready_to_projects.sql`, `migrations/0004_add_project_id_to_documents.sql`
- **Servicio de memoria persistente:** `docker-compose.yml` (`engram`, `engram-proxy`)
- **SPA session storage:** `frontend/src/stores/authStore.ts` (Zustand)