#!/usr/bin/env bash
# =============================================================================
# enable-branch-protection.sh — aplica el checklist de docs/CI-CD.md
#
# CUÁNDO CORRERLO (orden importa):
#   1. Merge de PR #103 (chore/ci-pipeline) en development.
#   2. Al menos una corrida VERDE de los checks "test" y "frontend" en
#      development (un PR trivial de prueba sirve: los checks requeridos
#      que nunca reportaron dejan los PRs trabados en "Expected" para
#      siempre).
#   3. Recién entonces: bash scripts/enable-branch-protection.sh
#
# Qué configura (fuente: docs/CI-CD.md, sección Branch Protection Checklist):
#   development: PR obligatorio, 0 approvals, checks requeridos
#                [test, frontend], historia linear, sin force-push,
#                sin delete.
#   main:        PR obligatorio, 1 approval mínimo, dismiss stale reviews,
#                checks requeridos [test, smoke], incluye administradores,
#                historia linear, sin force-push, sin delete.
#
# La API de branch protection requiere admin del repo. El dueño (vos)
# podés correrlo directo; no es destructivo y es reversible desde
# Settings → Branches.
# =============================================================================
set -euo pipefail

REPO="${REPO:-danielCH26/arch-agent}"
DRY_RUN="${DRY_RUN:-1}"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "== DRY RUN (no aplica nada). Para ejecutar: DRY_RUN=0 $0"
fi

apply_protection() {
  local branch="$1" approvals="$2" enforce_admins="$3"
  shift 3
  local checks_json="[" 
  local first=1
  for c in "$@"; do
    [[ $first -eq 0 ]] && checks_json+=","
    checks_json+="{\"context\":\"${c}\"}"
    first=0
  done
  checks_json+="]"

  local payload
  payload=$(cat <<EOF
{
  "required_status_checks": {"strict": true, "contexts": ${checks_json}},
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
)

  echo "== ${branch}: ${approvals} approval(s), checks=$(echo "${checks_json}" | tr -d ' '), enforce_admins=${enforce_admins}"
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "${payload}" | python3 -m json.tool > /dev/null && echo "   payload JSON valido (dry-run)"
  else
    gh api -X PUT "repos/${REPO}/branches/${branch}/protection" --input - <<< "${payload}" > /dev/null \
      && echo "   OK aplicado"
  fi
}

# development: 0 approvals (staging, merge rápido), admins NO forzados
apply_protection "development" 0 false "test" "frontend"

# main: 1 approval mínimo, admins incluidos (nadie esquiva)
apply_protection "main" 1 true "test" "smoke"

echo "== Listo. Verificación visual: Settings → Branches."
