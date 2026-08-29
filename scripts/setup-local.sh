#!/usr/bin/env bash
# =============================================================================
# Setup local automatizado para arch-agent (post-migración Chainlit → SPA).
#
# Stack 100% en Docker. No requiere Python ni Node locales.
#
# Asume:
#   - Docker y docker compose instalados y corriendo
#   - git
#
# Uso:
#   bash scripts/setup-local.sh
#
# Re-ejecutable: detecta qué pasos ya se hicieron y los salta.
# =============================================================================

set -euo pipefail

# --- Paths ---------------------------------------------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- Colores -------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${BLUE}[setup]${NC} $*"; }
ok()    { echo -e "${GREEN}[  ok ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[ warn ]${NC} $*"; }
fail()  { echo -e "${RED}[fail ]${NC} $*" >&2; exit 1; }

# --- Helpers -------------------------------------------------------------
need() {
    command -v "$1" >/dev/null 2>&1 || fail "Falta dependencia: $1"
}

ensure_line_in_env() {
    local key="$1" value="$2"
    local env_file=".env"
    if grep -qE "^${key}=" "$env_file"; then
        return 0
    fi
    echo "${key}=${value}" >> "$env_file"
    log "  + ${key}=... agregada a .env"
}

wait_for_postgres() {
    log "Esperando que postgres-app acepte conexiones..."
    for i in {1..30}; do
        if docker compose exec -T postgres-app pg_isready -U asistente >/dev/null 2>&1; then
            ok "postgres-app listo (intento $i)"
            return 0
        fi
        sleep 2
    done
    fail "postgres-app no respondió en 60 segundos"
}

wait_for_backend() {
    log "Esperando que el backend FastAPI responda..."
    for i in {1..60}; do
        if curl -fsS -m 2 http://127.0.0.1:8000/docs >/dev/null 2>&1; then
            ok "backend listo (intento $i)"
            return 0
        fi
        sleep 2
    done
    fail "backend no respondió en 120 segundos. Revisa: docker compose logs backend"
}

# --- Pre-chequeos --------------------------------------------------------
need docker
need git

log "Directorio de trabajo: $ROOT"
log "Branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'no es git')"

# --- 1. .env desde .env.example -----------------------------------------
if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        cp .env.example .env
        ok ".env creado desde .env.example"
    else
        fail "No existe .env.example; no puedo crear .env"
    fi
else
    log ".env ya existe, lo conservo"
fi

# --- 2. JWT_SECRET_KEY (≥32 bytes base64) --------------------------------
if ! grep -qE "^JWT_SECRET_KEY=.+" .env; then
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null \
        || openssl rand -base64 48 | tr -d '+/' | head -c 48)
    ensure_line_in_env "JWT_SECRET_KEY" "$JWT_SECRET"
    ok "JWT_SECRET_KEY generada"
else
    log "JWT_SECRET_KEY ya presente"
fi

# --- 3. ENCRYPTION_KEY (Fernet) ------------------------------------------
if ! grep -qE "^ENCRYPTION_KEY=.+" .env; then
    ENC_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
        || echo "$(openssl rand -base64 32)")
    ensure_line_in_env "ENCRYPTION_KEY" "$ENC_KEY"
    ok "ENCRYPTION_KEY generada"
else
    log "ENCRYPTION_KEY ya presente"
fi

# --- 4. docker compose up -------------------------------------------------
log "Construyendo imágenes Docker (backend + spa)..."
docker compose build backend spa 2>&1 | tail -10

log "Levantando stack completo..."
docker compose up -d postgres-app spa engram engram-proxy
docker compose up -d backend

wait_for_postgres

# --- 5. Init DB + migraciones dentro del contenedor backend --------------
if docker compose exec -T backend true >/dev/null 2>&1; then
    log "Verificando schema de DB..."
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
    export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres-app:5432/${POSTGRES_DB}"

    docker compose exec -T -e DATABASE_URL="$DATABASE_URL" backend \
        python3 scripts/init_db.py || \
        warn "init_db falló (puede ser normal si ya hay tablas)"

    docker compose exec -T -e DATABASE_URL="$DATABASE_URL" backend \
        python3 migrations/run_migrations.py || \
        warn "Migraciones fallaron (puede ser normal si ya están aplicadas)"
fi

# --- 6. Esperar backend ---------------------------------------------------
wait_for_backend

# --- 7. Resumen final ----------------------------------------------------
cat <<EOF

${GREEN}============================================================${NC}
${GREEN}Setup local completo${NC}
${GREEN}============================================================${NC}

Servicios disponibles:

  - Frontend SPA:  http://localhost:5173
  - Backend API:   http://localhost:8000
  - Swagger:       http://localhost:8000/docs
  - Langfuse:      http://localhost:3000

Stack del backend (Docker):

  - FastAPI + uvicorn
  - LangChain + langchain-community + langchain-postgres
  - sentence-transformers CPU-only (multilingual-e5-small ready)
  - pypdf para PDFs nativos
  - PGVector para RAG

Próximos pasos:

  1. Abrí http://localhost:5173 y registrate (botón "Registrarse")
     Username: cualquiera (ej. testuser)
     Email:    test@test.com
     Password: 8+ chars, 1 mayúscula, 1 número, 1 símbolo (ej. Test1234!)

  2. (Opcional) Configurar tu LLM desde la UI:
     Settings → LLM Config

  3. Para ver logs:
     docker compose logs -f backend
     docker compose logs -f spa

EOF
