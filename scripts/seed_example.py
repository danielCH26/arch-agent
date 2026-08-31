"""
Seed del caso de ejemplo end-to-end.

Issue: Caso de ejemplo (seed)
Responsable: Sofía
Sprint: 1

Crea un proyecto de ejemplo completo — "Sistema de Gestión de Tareas" —
que recorre las 4 fases reales del flujo (ver AVAILABLE_PHASES en
app/api/projects.py): requerimientos, propuesta, refinamiento, revision.

Nota de esquema: `sessions` tiene una sola fila por usuario (UNIQUE en
user_id) con el progreso guardado en `engram_state` (JSONB) y la fase
activa en `active_phase`. El contenido de cada fase vive como una clave
dentro de ese mismo JSON.

Nota (fix, issue [F05]): las primeras versiones de este seed usaban
nombres de fase en inglés (elicitation/proposal/diagram/tradeoffs) que no
coincidían con AVAILABLE_PHASES, y guardaban la aprobación como una clave
suelta dentro de engram_state en vez de usar la tabla `approvals` real
(que no existía todavía cuando se escribió este seed por primera vez).
Corregido: los 4 nombres de fase ahora coinciden con AVAILABLE_PHASES, y
cada aprobación se registra como una fila real en `approvals` -- el mismo
mecanismo que usa app/api/elicitation.py.

El contenido de la fase "requerimientos" además sigue exactamente la
forma que produce app/core/elicitation_agent.py (preguntas_respuestas,
pending_question, resumen con problema/usuarios_y_escala/requerimientos_
funcionales/requerimientos_no_funcionales/restricciones), para que el
proyecto demo sea un ejemplo fiel del flujo real, no solo una aproximación.

Requiere que scripts/seed_patterns.py ya se haya ejecutado (usa los
patrones cargados en architect_patterns para la fase de propuesta).

Nota (A1, revisión de PR): demo_user tiene is_demo_user=TRUE y un
password_hash que NO es un hash bcrypt real ("seed-demo-not-a-real-hash").
Este usuario no debe poder autenticarse nunca -- cualquier endpoint de
login debe filtrar explícitamente is_demo_user=TRUE antes de intentar
bcrypt.checkpw() contra su hash.

Nota (A3, revisión de PR): el proyecto demo tiene is_demo=TRUE. Los
endpoints que listan proyectos de un usuario real deben excluirlo.

Uso:
    docker compose exec backend python scripts/seed.py
    (o, individual: python scripts/seed_example.py)
"""

import json
import sys

from seed_common import connect_db, log
from seed_patterns import embed_query, to_pgvector_literal

DEMO_USERNAME = "demo_user"
DEMO_EMAIL = "demo@arch-agent.local"
PROJECT_NAME = "Sistema de Gestión de Tareas"
PROJECT_DESCRIPTION = (
    "Aplicación para que equipos pequeños creen, asignen y den seguimiento "
    "a tareas, con notificaciones cuando cambia el estado de una tarea."
)

# Fases reales, en orden (ver AVAILABLE_PHASES en app/api/projects.py).
EXPECTED_PHASES = ["requerimientos", "propuesta", "refinamiento", "revision"]

# Resumen que representaría lo que el agente entendió tras la elicitación;
# se usa como query para recuperar patrones relevantes por similitud.
ELICITATION_SUMMARY = (
    "Sistema para gestionar tareas en equipos pequeños, con notificaciones "
    "en tiempo real cuando una tarea cambia de estado, bajo volumen de "
    "usuarios concurrentes y sin necesidad de escalar módulos por separado "
    "en el corto plazo."
)

ELICITATION_QA = [
    {
        "pregunta": "¿Qué problema principal resuelve el sistema?",
        "respuesta": "Permitir que equipos pequeños creen, asignen y sigan tareas sin usar hojas de cálculo.",
    },
    {
        "pregunta": "¿Cuántos usuarios concurrentes esperan en el primer año?",
        "respuesta": "Entre 20 y 50 usuarios concurrentes, distribuidos en unos 5 equipos.",
    },
    {
        "pregunta": "¿Necesitan notificaciones en tiempo real?",
        "respuesta": "Sí, cuando una tarea cambia de estado o se asigna a alguien.",
    },
    {
        "pregunta": "¿Hay algún módulo que anticipen que crecerá mucho más rápido que el resto?",
        "respuesta": "No por ahora, todos los módulos crecerían al mismo ritmo.",
    },
    {
        "pregunta": "¿Qué tan crítico es el tiempo de salida al mercado (time-to-market)?",
        "respuesta": "Alto — es un proyecto de un semestre, preferimos simplicidad sobre escalabilidad prematura.",
    },
]

# Misma forma que app/core/elicitation_agent.SUMMARY_SYSTEM_PROMPT espera.
REQUIREMENTS_SUMMARY = {
    "problema": "Permitir que equipos pequeños creen, asignen y sigan tareas sin usar hojas de cálculo.",
    "usuarios_y_escala": "Entre 20 y 50 usuarios concurrentes, distribuidos en unos 5 equipos.",
    "requerimientos_funcionales": [
        "Crear, asignar y dar seguimiento a tareas",
        "Notificar cuando una tarea cambia de estado o se asigna a alguien",
    ],
    "requerimientos_no_funcionales": [
        "Notificaciones en tiempo real",
        "Simplicidad sobre escalabilidad prematura (proyecto de un semestre)",
    ],
    "restricciones": [
        "Alcance de un semestre académico",
        "Equipo de 4 personas",
    ],
}

DIAGRAM_MERMAID = (
    "graph TD\n"
    "    A[Cliente web] --> B[API de tareas]\n"
    "    B --> C[Capa de logica de negocio]\n"
    "    C --> D[(Base de datos)]\n"
    "    C --> E[Servicio de notificaciones]\n"
    "    E --> A\n"
)

TRADEOFFS = {
    "patron_elegido": "Arquitectura en capas (Layered)",
    "ventajas": [
        "Curva de aprendizaje baja para un equipo de 4 personas en un semestre",
        "Despliegue único, sin complejidad de infraestructura distribuida",
    ],
    "desventajas": [
        "Escalar el servicio de notificaciones por separado requeriría refactor futuro",
        "Menos aislamiento entre módulos que una arquitectura hexagonal o de microservicios",
    ],
}


def ensure_demo_user(conn) -> int:
    """Crea (o reutiliza) el usuario de ejemplo. Devuelve su id."""
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = %s", (DEMO_USERNAME,))
    row = cur.fetchone()
    if row:
        user_id = row[0]
        # Auto-reparación: si este usuario se creó antes de que existiera
        # la columna is_demo_user (A1), lo corrige en vez de dejarlo con
        # el flag en FALSE.
        cur.execute(
            "UPDATE users SET is_demo_user = TRUE WHERE id = %s AND is_demo_user = FALSE",
            (user_id,),
        )
        return user_id

    cur.execute(
        """
        INSERT INTO users (username, email, password_hash, is_demo_user)
        VALUES (%s, %s, %s, TRUE)
        RETURNING id
        """,
        (DEMO_USERNAME, DEMO_EMAIL, "seed-demo-not-a-real-hash"),
    )
    user_id = cur.fetchone()[0]
    log(f"Usuario demo creado (id={user_id})", "OK")
    return user_id


def ensure_demo_project(conn, user_id: int) -> int:
    """Crea (o reutiliza) el proyecto de ejemplo. Devuelve su id."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM projects WHERE user_id = %s AND name = %s",
        (user_id, PROJECT_NAME),
    )
    row = cur.fetchone()
    if row:
        project_id = row[0]
        # Auto-reparación: mismo caso que en ensure_demo_user, para is_demo (A3).
        cur.execute(
            "UPDATE projects SET is_demo = TRUE WHERE id = %s AND is_demo = FALSE",
            (project_id,),
        )
        return project_id

    cur.execute(
        """
        INSERT INTO projects
            (user_id, name, description, status, current_phase, is_demo)
        VALUES (%s, %s, %s, 'active', %s, TRUE)
        RETURNING id
        """,
        (user_id, PROJECT_NAME, PROJECT_DESCRIPTION, EXPECTED_PHASES[0]),
    )
    project_id = cur.fetchone()[0]
    log(f"Proyecto de ejemplo creado (id={project_id})", "OK")
    return project_id


def ensure_demo_session(conn, user_id: int, project_id: int):
    """
    Obtiene (o crea) la única sesión del usuario. Devuelve (session_id,
    engram_state actual como dict).
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT id, engram_state FROM sessions WHERE user_id = %s",
        (user_id,),
    )
    row = cur.fetchone()
    if row:
        return row[0], (row[1] or {})

    cur.execute(
        """
        INSERT INTO sessions (user_id, project_id, active_phase, engram_state)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (user_id, project_id, EXPECTED_PHASES[0], json.dumps({})),
    )
    session_id = cur.fetchone()[0]
    log(f"Sesión de ejemplo creada (id={session_id})", "OK")
    return session_id, {}


def save_phase(conn, session_id: int, engram_state: dict, phase: str, active_phase: str):
    """Persiste engram_state (ya con la fase actualizada) y mueve active_phase."""
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE sessions
        SET engram_state = %s, active_phase = %s, last_seen_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (json.dumps(engram_state), active_phase, session_id),
    )
    log(f"Fase '{phase}' guardada en engram_state", "OK")


def set_project_phase(conn, project_id: int, phase: str, phase_ready: bool):
    """
    Actualiza current_phase/phase_ready -- mismos campos que usa
    app/api/projects.py (/phase, /advance) y app/api/elicitation.py
    (/elicitation/decision) en el código real.
    """
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE projects
        SET current_phase = %s, phase_ready = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (phase, phase_ready, project_id),
    )


def record_approval(conn, session_id: int, phase: str, feedback: str):
    """
    Inserta una fila en `approvals` (issue [F05] Elicitación guiada +
    aprobación) -- mismo mecanismo real que usa
    app/api/elicitation.py::decide_elicitation.

    Idempotente por (session_id, phase): si ya existe una aprobación para
    esta fase en esta sesión, no la duplica.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM approvals WHERE session_id = %s AND phase = %s",
        (session_id, phase),
    )
    if cur.fetchone():
        return
    cur.execute(
        """
        INSERT INTO approvals (session_id, phase, decision, feedback)
        VALUES (%s, %s, 'approved', %s)
        """,
        (session_id, phase, feedback),
    )
    log(f"Aprobación registrada en 'approvals' para fase '{phase}'", "OK")


def retrieve_relevant_patterns(conn, top_k: int = 3):
    """
    Consulta architect_patterns por similitud usando el resumen de
    elicitación como query. Es, a la vez, el paso de 'propuesta' del caso
    de ejemplo y la verificación en vivo de que los patrones del RAG son
    consultables (criterio de aceptación del issue del seed).
    """
    query_vector = to_pgvector_literal(embed_query(ELICITATION_SUMMARY))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pattern_name, category, embedding <-> %s::vector AS distance
        FROM architect_patterns
        ORDER BY distance ASC
        LIMIT %s
        """,
        (query_vector, top_k),
    )
    results = cur.fetchall()
    if not results:
        log(
            "architect_patterns está vacía — ejecuta primero scripts/seed_patterns.py",
            "ERROR",
        )
        sys.exit(1)

    log("Patrones recuperados por similitud para la propuesta:")
    for name, category, distance in results:
        log(f"  - {name} ({category}) — distancia: {distance:.4f}")

    return [{"pattern_name": n, "category": c} for n, c, _ in results]


def seed_example_project(conn) -> tuple:
    user_id = ensure_demo_user(conn)
    project_id = ensure_demo_project(conn, user_id)
    session_id, engram_state = ensure_demo_session(conn, user_id, project_id)

    # --- Fase 1: requerimientos (elicitación) ---------------------------
    engram_state["requerimientos"] = {
        "preguntas_respuestas": ELICITATION_QA,
        "pending_question": None,
        "resumen": REQUIREMENTS_SUMMARY,
    }
    save_phase(conn, session_id, engram_state, "requerimientos", active_phase="propuesta")
    record_approval(
        conn, session_id, "requerimientos",
        "Requerimientos completos, se aprueba avanzar a propuesta.",
    )
    set_project_phase(conn, project_id, "propuesta", phase_ready=False)

    # --- Fase 2: propuesta (consulta real al RAG) -----------------------
    relevant_patterns = retrieve_relevant_patterns(conn)
    engram_state["propuesta"] = {
        "patrones_consultados": relevant_patterns,
        "patron_recomendado": relevant_patterns[0]["pattern_name"],
    }
    save_phase(conn, session_id, engram_state, "propuesta", active_phase="refinamiento")
    record_approval(
        conn, session_id, "propuesta",
        "Propuesta alineada con el alcance de un semestre, se aprueba.",
    )
    set_project_phase(conn, project_id, "refinamiento", phase_ready=False)

    # --- Fase 3: refinamiento (diagrama) ---------------------------------
    engram_state["refinamiento"] = {"diagrama_mermaid": DIAGRAM_MERMAID}
    save_phase(conn, session_id, engram_state, "refinamiento", active_phase="revision")
    record_approval(
        conn, session_id, "refinamiento",
        "Diagrama claro, se aprueba sin cambios.",
    )
    set_project_phase(conn, project_id, "revision", phase_ready=False)

    # --- Fase 4: revision (trade-offs) -------------------------------------
    engram_state["revision"] = dict(TRADEOFFS)
    save_phase(conn, session_id, engram_state, "revision", active_phase="revision")
    record_approval(
        conn, session_id, "revision",
        "Trade-offs entendidos y aceptados por el equipo.",
    )
    # Última fase: no hay a dónde avanzar, pero sí queda "lista".
    set_project_phase(conn, project_id, "revision", phase_ready=True)

    return project_id, user_id, session_id


def verify_end_to_end(conn, project_id: int, user_id: int, session_id: int):
    """
    Verifica que el caso de ejemplo cubre las 4 fases y quedó aprobado
    etapa por etapa en la tabla `approvals` real -- esto vuelve verificable
    el criterio de aceptación 'demuestra todas las fases del flujo'.
    """
    cur = conn.cursor()
    cur.execute("SELECT engram_state FROM sessions WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        log("La sesión de ejemplo no tiene engram_state", "ERROR")
        sys.exit(1)

    engram_state = row[0]
    missing = [p for p in EXPECTED_PHASES if p not in engram_state]
    if missing:
        log(f"Faltan fases en engram_state: {missing}", "ERROR")
        sys.exit(1)

    cur.execute(
        """
        SELECT COUNT(DISTINCT phase) FROM approvals
        WHERE session_id = %s AND decision = 'approved'
        """,
        (session_id,),
    )
    approved_count = cur.fetchone()[0]
    if approved_count < len(EXPECTED_PHASES):
        log(
            f"Solo {approved_count}/{len(EXPECTED_PHASES)} fases tienen "
            "aprobación registrada en 'approvals'",
            "ERROR",
        )
        sys.exit(1)

    log(
        f"Caso de ejemplo completo: {len(EXPECTED_PHASES)}/4 fases en engram_state, "
        f"{approved_count}/4 aprobaciones reales en 'approvals'",
        "OK",
    )


def main():
    log("=" * 60)
    log("Seed del caso de ejemplo end-to-end")
    log("=" * 60)
    conn = connect_db()
    try:
        project_id, user_id, session_id = seed_example_project(conn)
        verify_end_to_end(conn, project_id, user_id, session_id)
        log("=" * 60)
        log("Seed de ejemplo cargado correctamente ✓", "OK")
        log("=" * 60)
    finally:
        conn.close()


if __name__ == "__main__":
    main()