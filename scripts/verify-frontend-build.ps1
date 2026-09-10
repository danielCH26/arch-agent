# =============================================================================
# scripts/verify-frontend-build.ps1 - Windows companion of
# scripts/verify-frontend-build.sh
# =============================================================================
# PR #76 review fix #6b: makes ``npm run build`` a first-class verify step
# on Windows hosts where bash isn't the default shell.
#
# Usage:
#     powershell -ExecutionPolicy Bypass -File scripts\verify-frontend-build.ps1
#
# Behaviour mirrors the bash version 1:1 - runs ``tsc && vite build``
# against frontend/. Mirrors the same exit-code contract:
#     0  build / type-check succeeded
#     1  npm run build failed
#     2  could not find Node on PATH
# =============================================================================

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Resolve-Path (Join-Path $ScriptDir "..")
$FrontDir  = Join-Path $Root "frontend"

function Log($msg)   { Write-Host "[verify-frontend-build] $msg" -ForegroundColor Yellow }
function Ok($msg)    { Write-Host "[verify-frontend-build] $msg" -ForegroundColor Green }
function Fail($msg)  { Write-Host "[verify-frontend-build] $msg" -ForegroundColor Red; exit 1 }

# --- pre-checks -----------------------------------------------------------

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail "Node is not on PATH. Install Node 20+ (or run 'docker compose build spa' which uses the in-image Node)."
}

Push-Location $FrontDir
try {
    if (-not (Test-Path node_modules)) {
        Log "node_modules missing in frontend/; running 'npm ci' first"
        npm ci --no-audit --no-fund | Out-Null
    }

    Log "Running 'npm run build' (tsc --noEmit + vite build) ..."
    # Use ``&`` (the call operator) on the ``npm.cmd`` shim so the cmd
    # interpreter runs npm with the right argv handling. Direct
    # ``Start-Process -FilePath npm`` chokes on a 32/64 mismatch.
    & npm.cmd run build --silent
    if ($LASTEXITCODE -ne 0) {
        Fail "'npm run build' failed with exit code $LASTEXITCODE; review the tsc output above"
    }
    Ok "'npm run build' succeeded; production bundle emitted under frontend/dist/"
    Ok "verify-frontend-build: PASS"
}
finally {
    Pop-Location
}
