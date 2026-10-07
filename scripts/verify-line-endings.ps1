# =============================================================================
# scripts/verify-line-endings.ps1 - Windows companion of
# scripts/verify-line-endings.sh
# =============================================================================
# PR #76 review fix: detects stale Windows working trees whose tracked text
# files still hold CRLF even though .gitattributes mandates LF
# (``*.sh text eol=lf``, etc.). Git considers those files "unchanged" (the
# clean filter normalizes the comparison), so ``git status`` stays CLEAN and
# git never re-smudges them. The classic crash: a stale CRLF
# infrastructure/puppeteer-mcp/entrypoint.sh makes the puppeteer-mcp sidecar
# crash-loop with ``exec /entrypoint.sh: no such file or directory``
# (Restarting 255).
#
# Usage:
#     powershell -ExecutionPolicy Bypass -File scripts\verify-line-endings.ps1
#
# What it checks (one line per tracked file from ``git ls-files --eol``):
#     1. INDEX-POLLUTION:  i/crlf or i/mixed      -> FAIL (the committed blob
#        itself is not pure LF; fix the repo content, not the checkout)
#     2. STALE-WORKTREE:   attr contains eol=lf AND w/crlf -> FAIL
#        Files without attributes (``attr/``) are skipped for rule 2:
#        core.autocrlf may legitimately give them CRLF in the working copy.
#
# Exit codes:
#     0  all tracked files pass
#     1  at least one file failed a rule (per-file report printed)
#     2  git unavailable or not inside a git work tree
# =============================================================================

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Resolve-Path (Join-Path $ScriptDir "..")

function Fail($msg) { Write-Host "[verify-line-endings] $msg" -ForegroundColor Red }
function Ok($msg)   { Write-Host "[verify-line-endings] $msg" -ForegroundColor Green }

# --- pre-checks: git present + inside a work tree ---------------------------

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git is not on PATH; cannot verify line endings"
    exit 2
}

git -C $Root rev-parse --is-inside-work-tree 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Fail "'$Root' is not inside a git work tree; run this script from a git checkout"
    exit 2
}

# --- parse ``git ls-files --eol`` --------------------------------------------
#
# Line shape:  i/<eol> w/<eol> <attr fields...>\t<path>
# The attr field may contain spaces (``attr/text eol=lf``) or be empty
# (``attr/``), and the path starts after the LAST tab - so split on tab,
# never on plain whitespace.
$eolLines = @(& git -C $Root ls-files --eol 2>$null)
if ($LASTEXITCODE -ne 0) {
    Fail "'git ls-files --eol' failed with exit code $LASTEXITCODE"
    exit 2
}

$failures = New-Object System.Collections.Generic.List[string]
$checked  = 0
$skipped  = 0

foreach ($line in $eolLines) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }

    $tabParts = $line -split "`t"
    if ($tabParts.Count -lt 2) { continue }   # malformed line, no path
    $path = $tabParts[$tabParts.Count - 1]
    $meta = ($tabParts[0..($tabParts.Count - 2)]) -join " "

    $tokens = @($meta -split "\s+" | Where-Object { $_ -ne "" })
    if ($tokens.Count -lt 2) { continue }     # malformed line, no i/ + w/

    $indexEol = $tokens[0]                    # i/lf | i/crlf | i/mixed | i/none
    $workEol  = $tokens[1]                    # w/lf | w/crlf | w/mixed | w/none
    $attr     = ""
    if ($tokens.Count -gt 2) {
        $attr = ($tokens[2..($tokens.Count - 1)]) -join " "
    }

    $checked++

    # Rule 1: index pollution - the committed blob itself is not pure LF.
    if ($indexEol -eq "i/crlf" -or $indexEol -eq "i/mixed") {
        $failures.Add("INDEX-POLLUTION  $indexEol $workEol  $path")
        continue
    }

    # Files without attributes: skip the stale-worktree rule (autocrlf may
    # legitimately produce CRLF in the working copy for them).
    if ([string]::IsNullOrEmpty($attr) -or $attr -eq "attr/") {
        $skipped++
        continue
    }

    # Rule 2: stale working tree - .gitattributes promises LF but the local
    # working copy still holds CRLF from a pre-.gitattributes checkout.
    if (($attr -match "(^|\s)eol=lf(\s|$)") -and $workEol -eq "w/crlf") {
        $failures.Add("STALE-WORKTREE   $indexEol $workEol  $path")
    }
}

# --- report ------------------------------------------------------------------

foreach ($f in $failures) {
    Fail "FAIL $f"
}

Write-Host ""
if ($failures.Count -gt 0) {
    Fail "$($failures.Count) file(s) failed line-ending checks (checked: $checked, skipped: $skipped without attributes)."
    Fail "Stale working-tree files make Docker entrypoints crash-loop ('exec ...: no such file or directory')."
    Write-Host "[verify-line-endings] Recovery per stale file:" -ForegroundColor Yellow
    Write-Host "[verify-line-endings]   git rm --cached <path> ; git checkout HEAD -- <path>" -ForegroundColor Yellow
    exit 1
}

Ok "checked $checked file(s) ($skipped skipped without attributes); index is LF-clean and no stale CRLF working-tree files found."
Ok "verify-line-endings: PASS"
