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
#
# The ``lib*`` set below is the canonical ``@sparticuz/chromium`` / headless
# Chromium on Debian-slim list. Each one fixes a known crash signature on a
# fresh ``node:20-bookworm-slim`` image:
#
#   libnss3, libnssutil3, libsmime3, libnssckbi.so  -- TLS / cert chain
#   libatk1.0-0, libatk-bridge2.0-0                  -- accessibility stack
#   libatspi2.0-0                                   -- AT-SPI bus
#   libcups2                                        -- printer enumeration
#   libdbus-1-3                                     -- D-Bus (Chromium IPC)
#   libxcomposite1, libxdamage1, libxfixes3,
#   libxrandr2, libxkbcommon0                       -- X11 window system
#   libxext6, libxi6, libxrender1                   -- X11 extensions
#   libxtst6, libxshmfence1                         -- input + GPU fences
#   libxss1                                         -- X screensaver (used by puppeteer)
#   libgbm1, libpangocairo-1.0-0, libpango-1.0-0,
#   libcairo2                                       -- renderers
#   libasound2                                      -- ALSA audio
#   fonts-liberation                                -- Latin font fallback (Mermaid glyphs)
#
# Without ``libxcomposite1`` (PR #76 review finding) Chromium crashes on
# first paint with ``libXcomposite.so.1: cannot open shared object file``.
# ``fonts-liberation`` keeps Mermaid text rendering readable instead of as
# tofu boxes when no system font is installed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        fonts-liberation \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libatspi2.0-0 \
        libcups2 \
        libdbus-1-3 \
        libgbm1 \
        libnss3 \
        libnssutil3 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libsmime3 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxkbcommon0 \
        libxrandr2 \
        libxrender1 \
        libxshmfence1 \
        libxss1 \
        libxtst6 \
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