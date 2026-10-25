#!/usr/bin/env bash
# =============================================================================
# enable-branch-protection.sh — aplica el checklist de docs/CI-CD.md
#
# CUÁNDO CORRERLO (orden importa):
#   1. Merge de PR #103 (chore/ci-pipeline) en development.
#   2. Al menos una corrida VERDE de los checks requeridos: en development
#      basta el push del merge; en main, un PR contra main. Los required
#      checks que nunca reportaron dejan los PRs trabados en "Expected"; el
#      script lo verifica y aborta si falta alguno.
#   3. Recién entonces: DRY_RUN=0 bash scripts/enable-branch-protection.sh
#
# Qué configura (fuente: docs/CI-CD.md, sección Branch Protection Checklist):
#   development: PR obligatorio, 0 approvals, checks requeridos
#                [dev-backend-tests, dev-frontend-tests], historia lineal,
#                sin force-push, sin delete. Admins NO forzados.
#   main:        PR obligatorio, MAIN_APPROVALS approvals (default 1),
#                dismiss stale reviews, checks requeridos
#                [main-backend-tests, main-frontend-tests, main-docker-build],
#                admins incluidos (MAIN_ENFORCE_ADMINS, default true),
#                historia lineal, sin force-push, sin delete.
#   En ambas: strict=false (no obliga a re-sincronizar la rama con la base
#   antes de cada merge; con muchos PRs abiertos e historia lineal eso
#   obligaba a rebasear todo tras cada merge).
#
# OJO: el PUT REEMPLAZA toda la protección existente de la rama (no hace
# merge con lo que haya). Antes de aplicar, el script guarda la protección
# actual en un JSON de backup e imprime la ruta.
#
# Con enforce_admins=true y 1 approval, nadie (tampoco el dueño) mergea a
# main un PR propio sin la aprobación de otra persona. Es intencional; para
# un repo de una sola persona: MAIN_ENFORCE_ADMINS=false.
#
# Requiere admin del repo y `gh` autenticado (no hace falta en dry-run).
# =============================================================================
set -euo pipefail

REPO="${REPO:-danielCH26/arch-agent}"
DRY_RUN="${DRY_RUN:-1}"
MAIN_APPROVALS="${MAIN_APPROVALS:-1}"
MAIN_ENFORCE_ADMINS="${MAIN_ENFORCE_ADMINS:-true}"

DEV_CHECKS=(dev-backend-tests dev-frontend-tests)
MAIN_CHECKS=(main-backend-tests main-frontend-tests main-docker-build)

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "== DRY RUN (no aplica nada). Para ejecutar: DRY_RUN=0 $0"
fi

build_payload() {
  local approvals="$1" enforce_admins="$2"
  shift 2
  local checks_json="["
  local first=1
  for c in "$@"; do
    [[ $first -eq 0 ]] && checks_json+=","
    checks_json+="{\"context\":\"${c}\"}"
    first=0
  done
  checks_json+="]"

  cat <<EOF
{
  "required_status_checks": {"strict": false, "checks": ${checks_json}},
  "enforce_admins": ${enforce_admins},
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "required_approving_review_count": ${approvals}
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
}

# Verifica que cada check requerido ya reportó en verde sobre el commit dado.
require_green_checks() {
  local label="$1" sha="$2"
  shift 2
  local passed
  passed=$(gh api "repos/${REPO}/commits/${sha}/check-runs?per_page=100" \
    --jq '.check_runs[] | select(.conclusion == "success") | .name')
  local missing=0
  for c in "$@"; do
    if ! grep -qxF "${c}" <<< "${passed}"; then
      echo "   FALTA: '${c}' no tiene una corrida verde en ${label} (${sha:0:7})"
      missing=1
    fi
  done
  return "${missing}"
}

# ---------------------------------------------------------------------------
# Preflight: todo se valida ANTES de tocar cualquier rama, para no dejar
# development aplicado y main a medias.
# ---------------------------------------------------------------------------
DEV_PAYLOAD=$(build_payload 0 false "${DEV_CHECKS[@]}")
MAIN_PAYLOAD=$(build_payload "${MAIN_APPROVALS}" "${MAIN_ENFORCE_ADMINS}" "${MAIN_CHECKS[@]}")

PY=""
for candidate in python3 python; do
  "${candidate}" -c '' >/dev/null 2>&1 && { PY="${candidate}"; break; }
done
[[ -n "${PY}" ]] || { echo "ERROR: hace falta python3 para validar el JSON"; exit 1; }

for name in DEV_PAYLOAD MAIN_PAYLOAD; do
  "${PY}" -m json.tool > /dev/null <<< "${!name}" || { echo "ERROR: ${name} no es JSON válido"; exit 1; }
done

echo "== development: 0 approvals, checks=${DEV_CHECKS[*]}, enforce_admins=false"
echo "== main:        ${MAIN_APPROVALS} approval(s), checks=${MAIN_CHECKS[*]}, enforce_admins=${MAIN_ENFORCE_ADMINS}"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "   payloads JSON válidos (dry-run)"
  exit 0
fi

command -v gh >/dev/null 2>&1 || { echo "ERROR: gh CLI no está instalado"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "ERROR: gh no está autenticado; correr 'gh auth login'"; exit 1; }

ok=1
dev_sha=$(gh api "repos/${REPO}/commits/development" --jq .sha)
require_green_checks "development" "${dev_sha}" "${DEV_CHECKS[@]}" || ok=0

# pr-main corre en pull_request, así que los checks viven en el head del
# último PR contra main, no en main.
main_pr_sha=$(gh pr list --repo "${REPO}" --base main --state all --limit 1 --json headRefOid --jq '.[0].headRefOid // empty')
if [[ -z "${main_pr_sha}" ]]; then
  echo "   FALTA: no hay ningún PR contra main que haya corrido PR - Main"
  ok=0
else
  require_green_checks "el último PR contra main" "${main_pr_sha}" "${MAIN_CHECKS[@]}" || ok=0
fi

if [[ "${ok}" -ne 1 ]]; then
  echo "ERROR: abortado sin cambios. Esperar una corrida verde de los checks que faltan."
  exit 1
fi

# ---------------------------------------------------------------------------
# Aplicar (con backup de lo que había)
# ---------------------------------------------------------------------------
backup_dir=$(mktemp -d)
for branch in development main; do
  gh api "repos/${REPO}/branches/${branch}/protection" > "${backup_dir}/${branch}.json" 2>/dev/null \
    || echo '{}' > "${backup_dir}/${branch}.json"
done
echo "== Backup de la protección previa: ${backup_dir}"

gh api -X PUT "repos/${REPO}/branches/development/protection" --input - <<< "${DEV_PAYLOAD}" > /dev/null
echo "   OK development"
gh api -X PUT "repos/${REPO}/branches/main/protection" --input - <<< "${MAIN_PAYLOAD}" > /dev/null
echo "   OK main"

echo "== Listo. Verificación visual: Settings → Branches."
