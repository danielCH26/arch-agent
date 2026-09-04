"""
Seed del caso de ejemplo end-to-end.

Issue: Caso de ejemplo (seed)
Responsable: Sofía
Sprint: 1

Crea un proyecto de ejemplo completo — "Sistema de Gestión de Tareas" —
que recorre las 4 fases del flujo del agente (elicitación, propuesta,
diagrama, trade-offs).

Nota de esquema: `sessions` tiene una sola fila por usuario (UNIQUE en
user_id) con el progreso guardado en `engram_state` (JSONB) y la fase
activa en `active_phase`. Por eso el contenido y la aprobación de cada
fase (mismo mecanismo de Feature 3: Refinamiento y validación por etapas)
se guardan como una clave dentro de ese mismo JSON, no como filas nuevas.

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

EXPECTED_PHASES = ["elicitation", "proposal", "diagram", "tradeoffs"]


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
    log(f"Fase '{phase}' guardada en engram_state (aprobada)", "OK")


def update_project_phase(conn, project_id: int, phase: str):
    cur = conn.cursor()
    cur.execute(
        "UPDATE projects SET current_phase = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (phase, project_id),
    )


def retrieve_relevant_patterns(conn, top_k: int = 3):
    """
    Consulta architect_patterns por similitud usando el resumen de
    elicitación como query. Es, a la vez, el paso de 'propuesta' del caso
    de ejemplo y la verificación en vivo de que los patrones del RAG son
    consultables (criterio de aceptación del issue).
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

    # --- Fase 1: Elicitación -------------------------------------------
    engram_state["elicitation"] = {
        "preguntas_respuestas": ELICITATION_QA,
        "aprobacion": {
            "decision": "approved",
            "feedback": "Requerimientos completos, se aprueba avanzar a propuesta.",
        },
    }
    save_phase(conn, session_id, engram_state, "elicitation", active_phase="proposal")
    update_project_phase(conn, project_id, "proposal")

    # --- Fase 2: Propuesta (consulta real al RAG) -----------------------
    relevant_patterns = retrieve_relevant_patterns(conn)
    engram_state["proposal"] = {
        "patrones_consultados": relevant_patterns,
        "patron_recomendado": relevant_patterns[0]["pattern_name"],
        "aprobacion": {
            "decision": "approved",
            "feedback": "Propuesta alineada con el alcance de un semestre, se aprueba.",
        },
    }
    save_phase(conn, session_id, engram_state, "proposal", active_phase="diagram")
    update_project_phase(conn, project_id, "diagram")

    # --- Fase 3: Diagrama -------------------------------------------------
    engram_state["diagram"] = {
        "diagrama_mermaid": DIAGRAM_MERMAID,
        "aprobacion": {
            "decision": "approved",
            "feedback": "Diagrama claro, se aprueba sin cambios.",
        },
    }
    save_phase(conn, session_id, engram_state, "diagram", active_phase="tradeoffs")
    update_project_phase(conn, project_id, "tradeoffs")

    # --- Fase 4: Trade-offs -------------------------------------------------
    engram_state["tradeoffs"] = {
        **TRADEOFFS,
        "aprobacion": {
            "decision": "approved",
            "feedback": "Trade-offs entendidos y aceptados por el equipo.",
        },
    }
    save_phase(conn, session_id, engram_state, "tradeoffs", active_phase="tradeoffs")

    return project_id, user_id


def verify_end_to_end(conn, project_id: int, user_id: int):
    """
    Verifica que el caso de ejemplo cubre las 4 fases y quedó aprobado
    etapa por etapa — esto vuelve verificable el criterio de aceptación
    'demuestra todas las fases del flujo'.
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
        log(f"Faltan fases en el caso de ejemplo: {missing}", "ERROR")
        sys.exit(1)

    approved_count = sum(
        1
        for p in EXPECTED_PHASES
        if engram_state.get(p, {}).get("aprobacion", {}).get("decision") == "approved"
    )
    if approved_count < len(EXPECTED_PHASES):
        log(f"Solo {approved_count}/{len(EXPECTED_PHASES)} etapas quedaron aprobadas", "ERROR")
        sys.exit(1)

    log(
        f"Caso de ejemplo completo: {len(EXPECTED_PHASES)}/4 fases, "
        f"{approved_count}/4 aprobaciones registradas",
        "OK",
    )


def main():
    log("=" * 60)
    log("Seed del caso de ejemplo end-to-end")
    log("=" * 60)
    conn = connect_db()
    try:
        project_id, user_id = seed_example_project(conn)
        verify_end_to_end(conn, project_id, user_id)
        log("=" * 60)
        log("Seed de ejemplo cargado correctamente ✓", "OK")
        log("=" * 60)
    finally:
        conn.close()


if __name__ == "__main__":
    main()