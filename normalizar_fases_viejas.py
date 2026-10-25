"""
Los proyectos creados ANTES del cambio a fases fijas quedaron con
current_phase = "elicitación" (o cualquier otro texto libre viejo), que
ya no existe en la lista PHASES = ["requerimientos", "propuesta",
"refinamiento", "revision"]. Esto los deja atascados sin poder avanzar.

Este script los normaliza: cualquier proyecto cuya current_phase no esté
en la lista válida se resetea a "requerimientos" con phase_ready en False.

Correr una vez:
    python normalizar_fases_viejas.py
"""
from app.core.database import SessionLocal
from app.models.project import Project
from app.models.user import User  # noqa: F401 -- necesario para resolver la FK projects.user_id -> users.id

VALID_PHASES = {"requerimientos", "propuesta", "refinamiento", "revision"}

db = SessionLocal()
try:
    proyectos = db.query(Project).filter(
        (Project.current_phase.is_(None)) | (~Project.current_phase.in_(VALID_PHASES))
    ).all()

    if not proyectos:
        print("No hay proyectos con fase antigua/no reconocida. Nada que hacer.")
    else:
        for p in proyectos:
            print(f"Proyecto '{p.name}' (id {p.id}): '{p.current_phase}' -> 'requerimientos'")
            p.current_phase = "requerimientos"
            p.phase_ready = False
        db.commit()
        print(f"{len(proyectos)} proyecto(s) normalizado(s).")
finally:
    db.close()