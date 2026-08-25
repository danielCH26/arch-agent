# arch-agent

Asistente que guía a equipos de desarrollo en la definición de arquitecturas de software.

## Requisitos previos

- Docker Desktop en ejecución.
- Python y un entorno virtual con las dependencias de `requirements.txt`.
- Un archivo `.env` configurado. **Antes de continuar**, copiar `.env.example` a `.env` y completar los valores necesarios de POSTGRES_USER= y POSTGRES_DB=:

  ```powershell
  Copy-Item .env.example .env 
  ```

  Sin este paso, los comandos de las siguientes secciones (Docker, PostgreSQL) fallarán o usarán valores por defecto incorrectos.

## Iniciar el entorno

Desde la raíz del proyecto, con el `.env` ya creado:

```powershell
docker compose up -d
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn server:app --reload
```

Abrir `http://localhost:8000/register` para crear un usuario. Después, ingresar al chat en `http://localhost:8000/chainlit` con esas credenciales.

Para confirmar que los servicios requeridos están activos:

```powershell
docker compose ps postgres-app engram engram-proxy
```

## Pruebas de aceptación — sesión persistente

**Historia de usuario:** Como usuario, quiero que el sistema recuerde mi sesión para continuar donde quedé sin perder progreso.

**Responsable:** Laura

**Labels:** `user-story`, `sprint-1`, `backend`

### Alcance implementado

Al terminar una conversación, la aplicación guarda la sesión del usuario en PostgreSQL. Al volver a abrir el chat, recupera el proyecto y la fase activa. La tabla usada es `sessions`.

La aplicación usa PostgreSQL como fuente de verdad para el proyecto y la fase; Engram persiste el contexto resumido de cada sesión. Si Engram no está disponible, la aplicación conserva la recuperación desde PostgreSQL y registra una advertencia sin bloquear al usuario.

### Estado actual del proyecto activo

> Requiere que el entorno ya esté levantado (ver sección "Iniciar el entorno" arriba).

La fase se guarda inmediatamente con el comando `/set_fase`, incluso si la pestaña se recarga. Sin embargo, el flujo actual todavía no permite crear ni seleccionar proyectos desde el chat. Por ese motivo, mientras no se implemente ese flujo, la reconexión mostrará `Proyecto activo: sin asignar`.

La creación, selección y persistencia del proyecto activo corresponden a la **HU3**. Esta HU2 cubre la persistencia y recuperación de la sesión y de la fase activa.

Mientras se implementa la HU3, se puede crear un proyecto de prueba directamente en PostgreSQL:

1. Consultar el `id` asignado a tu usuario:

   ```powershell
   docker compose exec -T postgres-app psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB -c "SELECT id, username FROM users ORDER BY id;"
   ```

2. Insertar el proyecto asociándolo a tu `id` (reemplaza `1` por el número de tu `id` si es diferente):

   ```powershell
   docker compose exec -T postgres-app psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB -c "INSERT INTO projects (user_id, name) VALUES (1, 'Proyecto de prueba HU2');"
   ```

3. Guardar el identificador del proyecto seleccionado en `cl.user_session["project_id"]`.
4. Persistir ese identificador en `sessions.project_id` mediante `save_session_state`.

Cuando exista esa selección, la reconexión recuperará tanto el proyecto como la fase.

## Casos de prueba

Usar el mismo usuario en todos los casos. Para simular una fase, enviar en el chat el comando:

```text
/set_fase descubrimiento
```

Puede reemplazarse `descubrimiento` por el nombre de otra fase.

| ID | Criterio de aceptación | Pasos | Resultado esperado | Estado |
| --- | --- | --- | --- | --- |
| CA-01 | El sistema recupera la sesión activa al reconectar | 1. Iniciar sesión. 2. Enviar `/set_fase descubrimiento`. 3. Recargar o cerrar el chat. 4. Volver a iniciar sesión con el mismo usuario. | Aparece el mensaje “Bienvenida de vuelta” con la fase `descubrimiento`. | [ ] |
| CA-02 | Estado del proyecto persistido | 1. Crear y seleccionar un proyecto. 2. Guardar una fase. 3. Volver a iniciar sesión. 4. Consultar la tabla `sessions`. | Existe una única fila para el usuario y `project_id` conserva el proyecto seleccionado. | [ ] Pendiente: se implementa en HU3 |
| CA-03 | Fase activa del flujo recuperada | 1. Guardar una fase con `/set_fase`. 2. Cerrar y reabrir el chat. | La fase mostrada al volver a entrar coincide exactamente con la fase guardada. | [ ] |
| CA-04 | Sin inconsistencias al retomar | 1. Repetir el ciclo de guardar, cerrar y reconectar con dos fases distintas. 2. En la segunda vez usar, por ejemplo, `/set_fase diseño`. | Se muestra únicamente la última fase guardada (`diseño`); no se crean sesiones duplicadas ni se altera el proyecto. | [ ] |
| CA-05 | Memoria persistente con Engram | 1. Enviar `/set_fase descubrimiento`. 2. Cerrar el chat. 3. Volver a abrirlo. 4. Consultar las observaciones de Engram. | Engram conserva una observación de “Estado de sesión guardado” y la app consulta el contexto del proyecto al reconectar. | [ ] |

### Verificación en PostgreSQL

Ejecutar la siguiente consulta, reemplazando `tu_usuario`:

```powershell
docker compose exec postgres-app psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB -c "SELECT s.id, u.username, s.project_id, s.active_phase, s.engram_state, s.last_seen_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.username = 'tu_usuario';"
```

Validar que:

- Solo haya una fila por usuario.
- `project_id` y `active_phase` sean los valores vistos en el chat.
- `engram_state` contiene el identificador de sesión y la clave de memoria de Engram del usuario.

### Evidencia sugerida

Para cada criterio aprobado, adjuntar:

- Captura del mensaje al reconectar.
- Resultado de la consulta a `sessions`.
- Fecha, persona que ejecutó la prueba y estado final (aprobado/fallido).

## Componentes relacionados

- Persistencia de sesión: `app/core/session_store.py`
- Modelo ORM: `app/models/session.py`
- Recuperación y guardado al iniciar/cerrar el chat: `app.py`
- Esquema de PostgreSQL: `schema.sql`
- Servicio de memoria persistente: `docker-compose.yml` (`engram`)