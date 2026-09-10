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
#   libnss3                                              -- TLS / cert chain
#                                                         (includes nssutil + smime on bookworm)
#   libatk1.0-0, libatk-bridge2.0-0                      -- accessibility stack
#   libatspi2.0-0                                       -- AT-SPI bus
#   libcups2                                            -- printer enumeration
#   libdbus-1-3                                         -- D-Bus (Chromium IPC)
#   libxcomposite1, libxdamage1, libxfixes3,
#   libxrandr2, libxkbcommon0                           -- X11 window system
#   libxext6, libxi6, libxrender1                       -- X11 extensions
#   libxtst6, libxshmfence1                             -- input + GPU fences
#   libxss1                                             -- X screensaver (used by puppeteer)
#   libgbm1, libpangocairo-1.0-0, libpango-1.0-0,
#   libcairo2                                           -- renderers
#   libasound2                                          -- ALSA audio
#   fonts-liberation                                    -- Latin font fallback (Mermaid glyphs)
#
# Without ``libxcomposite1`` (PR #76 review finding) Chromium crashes on
# first paint with ``libXcomposite.so.1: cannot open shared object file``.
# ``fonts-liberation`` keeps Mermaid text rendering readable instead of as
# tofu boxes when no system font is installed.
#
# NOTE: ``libnssutil3`` / ``libsmime3`` are NOT separate packages on
# Debian bookworm-slim — they ship inside ``libnss3``. Listing them as
# standalone packages produces ``E: Unable to locate package libnssutil3``
# at build time.
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
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
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

# Pre-bake the MCP server + its transitive deps + the stdio->HTTP bridge.
# ``--no-audit`` keeps the install fast; ``--global`` keeps the runtime
# path short. PR #76 review fix #5: pre-install ``supergateway`` at image
# build time so ``entrypoint.sh`` does NOT need to fetch it on every
# container start via ``npx -y`` (an avoidable ~30 s cold-start + flakiness
# when the npm registry has an outage). The runtime ``npx supergateway``
# in entrypoint.sh picks up the global install from the PATH cache, so
# we keep the ``npx`` invocation (compat with future version bumps that
# may shadow it locally) but no longer pay the network round-trip on
# every boot.
RUN npm install -g --no-audit --no-fund \
    @modelcontextprotocol/server-puppeteer \
    supergateway

# Warm the MCP server cache so the first ``--version`` invocation at runtime
# does not pay the cold-start tax. Best-effort; failures here are non-fatal.
RUN npx -y @modelcontextprotocol/server-puppeteer --version >/dev/null 2>&1 || true
# Same warm-up for the bridge so the first ``/health`` probe doesn't have
# to resolve transitive deps at container start.
RUN npx -y supergateway --version >/dev/null 2>&1 || true

COPY entrypoint.sh /entrypoint.sh
# CRLF-safe: even though ``.gitattributes`` declares ``*.sh text eol=lf``
# at the repo root, Docker's COPY reads the build-context file, not the
# git index. A Windows checkout can land CRLF in the working copy, and
# the kernel's script loader refuses to exec a script whose shebang is
# ``#!/bin/sh\r`` (``no such file or directory`` on the kernel side).
# Strip CRs explicitly before chmod so this never breaks a build on a
# CRLF checkout.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 8931

ENTRYPOINT ["/entrypoint.sh"]