#!/bin/sh
# Arranque del backend: lo usan el CMD de backend/Dockerfile (Railway) y
# docker-compose.yml, así los dos entornos preparan la base igual.
#
# 1. Aplica schema.sql (idempotente) y las migraciones pendientes.
# 2. Copia las imágenes de los patrones del YAML a la base (migración 0024):
#    --images-only no carga el modelo de embeddings, tarda segundos.
# 3. Levanta uvicorn con exec, para que reciba las señales del contenedor.
#
# Si un paso falla, el contenedor sale con error en vez de arrancar contra una
# base desactualizada.
set -e

python scripts/init_db.py
python -m migrations.run_migrations
python scripts/seed_patterns.py --images-only
exec uvicorn server:app --host 0.0.0.0 --port 8000 --proxy-headers
