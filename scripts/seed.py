"""
Entrypoint único para cargar todo el seed del proyecto.

Issue: Caso de ejemplo (seed)
Responsable: Sofía
Sprint: 1

Ejecuta, en orden:
    1. scripts/seed_patterns.py — patrones de arquitectura (RAG)
    2. scripts/seed_example.py  — proyecto de ejemplo end-to-end

Uso:
    docker compose exec app python scripts/seed.py

Nota: requiere que la base de datos ya exista (scripts/init_db.py).
"""

import seed_example
import seed_patterns
from seed_common import log


def main():
    log("=" * 60)
    log("Seed completo del proyecto arch-agent")
    log("=" * 60)
    seed_patterns.main()
    seed_example.main()


if __name__ == "__main__":
    main()