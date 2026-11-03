#!/bin/sh
# Arranque del backend: lo usan el CMD de backend/Dockerfile (Railway) y
# docker-compose.yml, así los dos entornos preparan la base igual.
#
# 1. Aplica schema.sql (idempotente) y las migraciones pendientes.
# 2. Copia las imágenes de los patrones del YAML a la base (migración 0024):
#    --images-only no carga el modelo de embeddings, tarda segundos. Al final
#    siembra también las convenciones de repositorio (repo_convention_chunks).
# 3. Siembra el catálogo de nube (cloud_service_chunks), que ningún otro paso
#    llamaba: sin él la fase de despliegue no tiene catálogo que consultar y
#    el plan sale vacío en un entorno recién levantado.
# 4. Levanta uvicorn con exec, para que reciba las señales del contenedor.
#
# Si un paso falla, el contenedor sale con error en vez de arrancar contra una
# base desactualizada. El seed del catálogo de nube es la excepción: queda
# fuera de `set -e` a propósito, igual que el de convenciones, porque la app
# funciona sin él (solo se pierde la fase de despliegue) y no vale tirar abajo
# el arranque entero por eso.
set -e

python scripts/init_db.py
python -m migrations.run_migrations
python scripts/seed_patterns.py --images-only
python scripts/seed_cloud_catalog.py || echo "[WARN] El seed del catálogo de nube no terminó; la fase de despliegue no estará disponible hasta que corras: python scripts/seed_cloud_catalog.py"
exec uvicorn server:app --host 0.0.0.0 --port 8000 --proxy-headers
