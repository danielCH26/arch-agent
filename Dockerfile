# =============================================================================
# Dockerfile — Asistente de Arquitectura (F01)
# Imagen base para el servicio `app` (Chainlit + LangChain + MCPs)
# =============================================================================
FROM python:3.11-slim

# Evitar preguntas interactivas durante apt
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Instalar dependencias del sistema
# - Node.js y npm: para MCPs Puppeteer y Filesystem (via npx)
# - curl: para healthchecks y descargas
# - git: para algunas dependencias de Python
# - ca-certificates: para HTTPS
# - build-essential: para compilar extensiones nativas si hace falta
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    curl \
    git \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Instalar uv (gestor de paquetes Python ultrarrapido) - para MCP Fetch via uvx
RUN pip install --no-cache-dir uv

# Crear usuario no-root por seguridad
RUN useradd -m -u 1000 appuser

# Directorio de trabajo
WORKDIR /app

# Copiar requirements primero (mejor cache de Docker)
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# Pre-instalar MCPs via npx para que esten cacheados
# Esto evita descargas en runtime
RUN npm install -g \
    @modelcontextprotocol/server-puppeteer \
    @modelcontextprotocol/server-filesystem \
    && npm cache clean --force

# Pre-instalar MCP Fetch via uvx
RUN uv tool install mcp-server-fetch || echo 'mcp-server-fetch will install on first run'

# Copiar el codigo de la aplicacion
COPY --chown=appuser:appuser . /app

# Crear directorios necesarios para los volumenes
RUN mkdir -p /app/uploads /app/logs /app/models_cache && \
    chown -R appuser:appuser /app

# Cambiar a usuario no-root
USER appuser

# Exponer puerto de Chainlit
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Comando por defecto
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
