#!/usr/bin/env bash
# =============================================================================
# scripts/verify-frontend-build.sh
# =============================================================================
# PR #76 review fix #6b: makes ``npm run build`` a first-class verify step
# so the ``tsc --noEmit`` pass (Phase 1 of the ``build`` script in
# ``frontend/package.json``) is run on every PR. Catches dead-code drift
# that ``pnpm test:run`` misses (e.g. F13's
# ``_normaliseHistoryAttachments`` was declared in
# ``frontend/src/api/chat.ts`` but never called - ``tsc --noEmit`` did
# NOT fail because ``noUnusedLocals`` was off in tsconfig; ``tsc``
# itself, the Phase-2 strict-mode hook of ``npm run build``, fires
# only after the test gate).
#
# Usage:
#     bash scripts/verify-frontend-build.sh
#
# Behaviour:
#     1. Locally:  cd frontend && npm run build  (runs ``tsc && vite build``)
#     2. In a container-driven environment:  skipped with a notice if
#        ``node_modules`` is missing; the ``spa`` Docker image is built
#        separately by ``docker compose build spa`` and that pipeline
#        already runs ``npm run build``.
#
# Exit codes:
#     0  build / type-check succeeded
#     1  ``npm run build`` exited non-zero (TypeScript error or Vite failure)
#     2  this script was unable to find a usable runtime (no node, no
#        node_modules, no docker)
# =============================================================================

set -euo pipefail

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT/frontend"

log()    { echo "${YELLOW}[verify-frontend-build]${NC} $*"; }
ok()     { echo "${GREEN}[verify-frontend-build]${NC} $*"; }
fail()   { echo "${RED}[verify-frontend-build]${NC} $*" >&2; exit 1; }

# --- pre-checks -----------------------------------------------------------

# Prefer a Node on PATH (Linux/macOS/CI runners). On Windows hosts
# running through Git Bash the ``node.exe`` may not be reachable even
# though ``where node`` finds it; try the common install paths and
# temporarily add whichever one we find to PATH. If none of these
# work, fall through with a clear "use docker or powershell" message
# rather than a confusing exec error.
have_node=0
if command -v node >/dev/null 2>&1; then
    have_node=1
else
    for cand in \
        "/c/Program Files/nodejs/node.exe" \
        "/c/Program Files (x86)/nodejs/node.exe" \
        "/mnt/c/Program Files/nodejs/node.exe"; do
        if [[ -x "$cand" ]]; then
            cand_dir="$(dirname "$cand")"
            PATH="$cand_dir:$PATH"
            export PATH
            have_node=1
            log "Found Node at $cand (added to PATH for this run)"
            break
        fi
    done
fi

if [[ "$have_node" -ne 1 ]]; then
    fail "
'node' was not on PATH in this shell.

Run the verify step ONE of these ways instead:

  Linux / macOS / WSL2:
      cd frontend && npm run build

  Windows cmd / PowerShell (after this command tried bash):
      cd frontend ; npm run build

  Docker (preferred on a fresh clone):
      docker compose build spa   # the Dockerfile runs 'npm run build' as
                                 # part of the multi-stage build; a build
                                 # failure surfaces as a non-zero exit
                                 # from compose.
"
fi

cd "$FRONTEND_DIR"

if [[ ! -d node_modules ]]; then
    log "node_modules missing in frontend/; running 'npm ci' first"
    npm ci --no-audit --no-fund
fi

# --- run -----------------------------------------------------------------

log "Running 'npm run build' (tsc --noEmit + vite build) ..."

# Some Windows-with-Git-Bash setups ship a ``npm.cmd`` shim that does
# NOT survive bash invocation correctly (it triggers a WSL error path).
# Detect that pattern and fall through to the documented manual step
# rather than masking the real failure with our own exit code.
if ! command -v npm >/dev/null 2>&1; then
    fail "
'npm' was not found in this shell after the PATH fix.

This is most often the case on Windows hosts where a 'npm.cmd' shim is
on PATH but bash invokes it incorrectly. Run this verify step ONE of
these other ways instead:

  PowerShell (recommended on Windows):
      powershell -ExecutionPolicy Bypass -File scripts\\verify-frontend-build.ps1

  Docker (works on every host):
      docker compose build spa       # Dockerfile includes 'npm run build'

  Linux / macOS / WSL2 directly:
      cd frontend && npm run build
"
fi

# ``npm run build`` from frontend/package.json:
#   "build": "tsc && vite build",
# i.e. it FIRST runs the TypeScript compiler with no JS emit, which is the
# strict-mode hook that catches unused-locals, dead imports, and any
# shape drift on the public API of chat.ts / chatStore.ts. Only after
# tsc exits 0 does vite build the bundle.
if npm run build --silent; then
    ok "'npm run build' succeeded; production bundle emitted under frontend/dist/"
else
    fail "'npm run build' failed; review the tsc output above"
fi

# --- summary -------------------------------------------------------------

ok "verify-frontend-build: PASS"
log "future verify cycles should invoke 'bash scripts/verify-frontend-build.sh'"
log "before declaring the PR ready for review (commit convention per"
log "openSpec/puppeteer-mcp-integration/spec.md REQ-PMCP-5 + REQ-PMCP-7)."
