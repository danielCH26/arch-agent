#!/bin/sh
# =============================================================================
# Puppeteer MCP sidecar entrypoint (F13, issue #17).
#
# Activates the ``streamable_http`` transport on :8931 and points the upstream
# server at the OS Chromium binary installed by the Dockerfile. The
# ``--executable-path`` flag overrides the Puppeteer auto-download so we
# never ship a second Chromium in ``node_modules`` (keeps the image small).
# =============================================================================
set -e

echo "[puppeteer-mcp] starting @modelcontextprotocol/server-puppeteer on :8931 (streamable_http)"
exec npx -y @modelcontextprotocol/server-puppeteer \
    --port 8931 \
    --executable-path /usr/bin/chromium