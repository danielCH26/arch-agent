#!/usr/bin/env bash
# =============================================================================
# scripts/verify-line-endings.sh
# =============================================================================
# PR #76 review fix: detects stale working trees whose tracked text files
# still hold CRLF even though .gitattributes mandates LF (``*.sh text
# eol=lf``, etc.). Git considers those files "unchanged" (the clean filter
# normalizes the comparison), so ``git status`` stays CLEAN and git never
# re-smudges them. The classic crash: a stale CRLF
# infrastructure/puppeteer-mcp/entrypoint.sh makes the puppeteer-mcp sidecar
# crash-loop with ``exec /entrypoint.sh: no such file or directory``
# (Restarting 255).
#
# Usage:
#     bash scripts/verify-line-endings.sh
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

set -euo pipefail

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() { echo "${RED}[verify-line-endings]${NC} $*" >&2; }
ok()   { echo "${GREEN}[verify-line-endings]${NC} $*"; }

# --- pre-checks: git present + inside a work tree ---------------------------

if ! command -v git >/dev/null 2>&1; then
    fail "git is not on PATH; cannot verify line endings"
    exit 2
fi

if ! git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    fail "'$ROOT' is not inside a git work tree; run this script from a git checkout"
    exit 2
fi

# --- parse ``git ls-files --eol`` --------------------------------------------
#
# Line shape:  i/<eol> w/<eol> <attr fields...>\t<path>
# The attr field may contain spaces (``attr/text eol=lf``) or be empty
# (``attr/``), and the path starts after the LAST tab - so split on tab
# (awk ``split($0, a, "\t")`` equivalent: ${line##*$'\t'}), never on plain
# whitespace.
failures=0
checked=0
skipped=0

while IFS= read -r line; do
    if [[ -z "$line" ]]; then
        continue
    fi

    path="${line##*$'\t'}"
    meta="${line%%$'\t'*}"
    if [[ "$path" == "$line" ]]; then
        continue    # malformed line: no tab-delimited path
    fi

    # First two whitespace tokens are i/ and w/; the remainder is the attr
    # field (may itself contain spaces, e.g. ``attr/text eol=lf``).
    index_eol=""
    work_eol=""
    attr_rest=""
    # shellcheck disable=SC2086
    read -r index_eol work_eol attr_rest <<< "$meta" || true
    if [[ -z "$index_eol" || -z "$work_eol" ]]; then
        continue    # malformed line: missing i/ or w/ token
    fi

    checked=$((checked + 1))

    # Rule 1: index pollution - the committed blob itself is not pure LF.
    if [[ "$index_eol" == "i/crlf" || "$index_eol" == "i/mixed" ]]; then
        fail "FAIL INDEX-POLLUTION  $index_eol $work_eol  $path"
        failures=$((failures + 1))
        continue
    fi

    # Files without attributes: skip the stale-worktree rule (autocrlf may
    # legitimately produce CRLF in the working copy for them).
    if [[ -z "$attr_rest" || "$attr_rest" == "attr/" ]]; then
        skipped=$((skipped + 1))
        continue
    fi

    # Rule 2: stale working tree - .gitattributes promises LF but the local
    # working copy still holds CRLF from a pre-.gitattributes checkout.
    if [[ " $attr_rest " == *" eol=lf "* && "$work_eol" == "w/crlf" ]]; then
        fail "FAIL STALE-WORKTREE   $index_eol $work_eol  $path"
        failures=$((failures + 1))
    fi
done < <(git -C "$ROOT" ls-files --eol 2>/dev/null)

# --- report ------------------------------------------------------------------

echo ""
if [[ "$failures" -gt 0 ]]; then
    fail "$failures file(s) failed line-ending checks (checked: $checked, skipped: $skipped without attributes)."
    fail "Stale working-tree files make Docker entrypoints crash-loop ('exec ...: no such file or directory')."
    echo "${YELLOW}[verify-line-endings]${NC} Recovery per stale file:" >&2
    echo "${YELLOW}[verify-line-endings]${NC}   git rm --cached <path> ; git checkout HEAD -- <path>" >&2
    exit 1
fi

ok "checked $checked file(s) ($skipped skipped without attributes); index is LF-clean and no stale CRLF working-tree files found."
ok "verify-line-endings: PASS"
