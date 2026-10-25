#!/bin/sh
# =============================================================================
# Puppeteer MCP sidecar entrypoint (F13, issue #17).
#
# The upstream @modelcontextprotocol/server-puppeteer package (verified
# against version 2025.5.12) is stdio-only — it instantiates
# ``StdioServerTransport`` directly and accepts NO command-line flags at all.
# The original entrypoint tried ``--port 8931`` and ``--executable-path``,
# but both flags were silently ignored, and the process exited within ~40s
# when Docker closed its stdin.
#
# We therefore bridge stdio -> streamable_http with ``supergateway``:
#   - supergateway spawns the upstream puppeteer server on stdin/stdout,
#   - it re-exposes the same MCP frame on HTTP at :8931/mcp,
#   - the ``/health`` endpoint returns ``ok`` so docker-compose's existing
#     ``wget --spider http://127.0.0.1:8931/health`` probe can drive the
#     healthcheck unchanged.
#
# Chromium is auto-discovered from ``PUPPETEER_CACHE_DIR=/root/.cache/puppeteer``
# (the directory populated during ``npm install`` at build time). We do NOT
# pass ``--executable-path`` because that path is version-fragile — Chromium
# 131.x ships under ``chrome/linux-131.0.6778.204/chrome-linux64/chrome``
# and that directory name changes with every Puppeteer / Chromium bump.
# =============================================================================
set -e

echo "[puppeteer-mcp] starting supergateway on :8931 (streamable_http) with stdio bridge to server-puppeteer"
exec npx -y supergateway \
    --stdio "npx -y @modelcontextprotocol/server-puppeteer" \
    --port 8931 \
    --outputTransport streamableHttp \
    --stateful \
    --sessionTimeout 300000 \
    --streamableHttpPath /mcp \
    --healthEndpoint /health \
    --logLevel info