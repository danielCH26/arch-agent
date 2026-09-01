#!/usr/bin/env python3
"""
Seed idempotente de patrones de arquitectura para el RAG.

Uso:
    python scripts/seed_architect_patterns.py

El primer run puede tardar mientras descarga multilingual-e5-small.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.exc import IntegrityError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.database import SessionLocal
from app.core.embeddings import get_embeddings
from app.models.architect_pattern import ArchitectPattern


PATTERNS = [
    {
        "pattern_name": "Arquitectura de microservicios",
        "category": "distributed-systems",
        "description": (
            "Divide el sistema en servicios pequenos, desplegables de forma "
            "independiente y alineados a capacidades de negocio."
        ),
        "use_cases": "Dominios grandes, equipos autonomos, escalamiento independiente.",
        "tradeoffs": {
            "pros": ["despliegue independiente", "escalabilidad granular", "aislamiento de fallos"],
            "cons": ["complejidad operacional", "consistencia distribuida", "observabilidad mas exigente"],
        },
    },
    {
        "pattern_name": "Arquitectura hexagonal",
        "category": "application-architecture",
        "description": (
            "Aisla el dominio de frameworks, bases de datos e interfaces externas "
            "mediante puertos y adaptadores."
        ),
        "use_cases": "Sistemas con dominio rico, alta testeabilidad y cambios frecuentes de infraestructura.",
        "tradeoffs": {
            "pros": ["dominio testeable", "bajo acoplamiento", "facil cambio de adaptadores"],
            "cons": ["mas estructura inicial", "curva de aprendizaje"],
        },
    },
    {
        "pattern_name": "CQRS",
        "category": "data-architecture",
        "description": (
            "Separa modelos y rutas de escritura de los modelos de lectura para "
            "optimizar consultas y comandos de forma independiente."
        ),
        "use_cases": "Lecturas complejas, alta carga de consulta, auditoria de cambios.",
        "tradeoffs": {
            "pros": ["lecturas optimizadas", "separacion clara de responsabilidades"],
            "cons": ["eventual consistency", "mas componentes de sincronizacion"],
        },
    },
    {
        "pattern_name": "Event sourcing",
        "category": "data-architecture",
        "description": (
            "Persiste eventos inmutables como fuente de verdad y reconstruye el "
            "estado actual reproduciendo esos eventos."
        ),
        "use_cases": "Auditoria fuerte, historial completo, dominios financieros o transaccionales.",
        "tradeoffs": {
            "pros": ["auditoria completa", "replay de estado", "trazabilidad"],
            "cons": ["modelo mental complejo", "migracion de eventos", "consultas requieren proyecciones"],
        },
    },
    {
        "pattern_name": "Backend for Frontend",
        "category": "integration",
        "description": (
            "Crea backends especificos por experiencia cliente para adaptar datos, "
            "contratos y orquestacion a cada frontend."
        ),
        "use_cases": "Apps web y moviles con necesidades distintas o multiples canales.",
        "tradeoffs": {
            "pros": ["contratos optimizados por cliente", "menos logica en frontend"],
            "cons": ["posible duplicacion", "mas servicios que operar"],
        },
    },
]


def _pattern_text(pattern: dict) -> str:
    return "\n".join([
        pattern["pattern_name"],
        pattern["category"],
        pattern["description"],
        pattern["use_cases"],
        " ".join(pattern["tradeoffs"].get("pros", [])),
        " ".join(pattern["tradeoffs"].get("cons", [])),
    ])


def main() -> None:
    db = SessionLocal()
    try:
        existing_names = {
            row[0]
            for row in db.query(ArchitectPattern.pattern_name)
            .filter(ArchitectPattern.pattern_name.in_([p["pattern_name"] for p in PATTERNS]))
            .all()
        }
        new_patterns = [p for p in PATTERNS if p["pattern_name"] not in existing_names]
        if not new_patterns:
            print("No hay patrones nuevos para insertar.")
            return

        embeddings = get_embeddings().embed_documents([_pattern_text(p) for p in new_patterns])
        for pattern, embedding in zip(new_patterns, embeddings):
            db.add(ArchitectPattern(**pattern, embedding=embedding))
        db.commit()
        print(f"Patrones insertados: {len(new_patterns)}")
    except IntegrityError as e:
        db.rollback()
        raise SystemExit(f"No se pudieron insertar patrones: {e}") from e
    finally:
        db.close()


if __name__ == "__main__":
    main()
