"""El backend arranca igual en Docker Compose y en Railway (F29).

Railway despliega con ``backend/Dockerfile``; si el arranque solo estuviera en
el ``command`` de docker-compose.yml, producción quedaría sin migrar y sin las
imágenes de los patrones.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = "scripts/start_backend.sh"


def test_el_dockerfile_arranca_con_el_script_compartido():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    cmd = [line for line in dockerfile.splitlines() if line.startswith("CMD")]
    assert cmd == [f'CMD ["sh", "{START_SCRIPT}"]']


def test_compose_no_reemplaza_el_arranque_del_dockerfile():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "command" not in compose["services"]["backend"]


def test_el_script_migra_sincroniza_imagenes_y_levanta_uvicorn_en_orden():
    script = (ROOT / START_SCRIPT).read_text(encoding="utf-8")
    steps = [
        "set -e",
        "python scripts/init_db.py",
        "python -m migrations.run_migrations",
        "python scripts/seed_patterns.py --images-only",
        "exec uvicorn server:app",
    ]
    positions = [script.index(step) for step in steps]
    assert positions == sorted(positions)
    # Un CRLF rompe `sh` en el contenedor Linux.
    assert "\r" not in (ROOT / START_SCRIPT).read_bytes().decode("utf-8")
