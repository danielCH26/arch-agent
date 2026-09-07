# =============================================================================
# Puppeteer MCP sidecar (F13, issue #17).
#
# Stack:
#   - node:20-bookworm-slim
#   - Chromium + system libs (libnss3, libatk, libxss, libasound2, ...)
#   - @modelcontextprotocol/server-puppeteer (pre-baked, warm cache)
#   - exposes :8931/mcp over streamable_http transport
#
# Design notes:
#   - Persistent Chromium process per sidecar (single replica). No multi-replica
#   proxy: streamable_http runs on the sidecar directly (no stdio bridge).
#   - ``EXPOSE 8931`` documents the listener; docker-compose does NOT publish
#   the port to the host (backend reaches it on the docker network).
#   - Warm-on-start: pre-bake the MCP server during build so the first render
#   request does not pay the npm-install / puppeteer-launch latency.
#
# Build:
#   docker compose build puppeteer-mcp
# =============================================================================
FROM node:20-bookworm-slim

ENV NODE_ENV=production \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false \
    PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=false \
    PUPPETEER_CACHE_DIR=/root/.cache/puppeteer

# Chromium runtime dependencies + ca-certificates (HTTPS to upstream).
# ``fonts-liberation`` so Mermaid text renders with sane glyphs; without it
# headless Chromium falls back to tofu boxes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        fonts-liberation \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libgbm1 \
        libnss3 \
        libxss1 \
        wget \
    && rm -rf /var/lib/apt/lists/*

# Pre-bake the MCP server + its transitive deps. ``--no-audit`` keeps the
# install fast; ``--global`` keeps the runtime path short.
RUN npm install -g --no-audit --no-fund @modelcontextprotocol/server-puppeteer

# Warm the MCP server cache so the first ``--version`` invocation at runtime
# does not pay the cold-start tax. Best-effort; failures here are non-fatal.
RUN npx -y @modelcontextprotocol/server-puppeteer --version >/dev/null 2>&1 || true

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8931

ENTRYPOINT ["/entrypoint.sh"]