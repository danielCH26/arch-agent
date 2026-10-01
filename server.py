import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from app.auth.register import register_user
from app.auth.validators import ValidationError
from app.core.exceptions import (
    ArchAgentError,
    DatabaseConnectionError,
    DatabaseIntegrityError,
    FileInvalidFormatError,
    FileTooLargeError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    RAGEmbeddingError,
)
# RAGSearchError lives in app.core.rag (not in app.core.exceptions) and is only
# raised by the RAG endpoints — they handle it locally. The global handler
# does not need it.

load_dotenv()

templates = Jinja2Templates(directory="templates")
app = FastAPI(title="Arch Agent API", version="1.0.0")


# --- Global exception handlers ---------------------------------------------
# Soomri (F17 review, item 8) suggested "or better, use a global
# exception_handler". This is the better path: a single place that maps our
# typed ArchAgentError hierarchy (and the SQLAlchemy exceptions they wrap) to
# HTTPException, removing the per-endpoint @handle_*_errors decorators.
#
# The decorators still work (they wrap the function before FastAPI sees it).
# A future PR can drop them once the handlers above are battle-tested in CI.
_APP_AGENT_ERROR_MAPPING = {
    # DB
    DatabaseConnectionError: (503, "No pudimos conectar con la base de datos. Es un problema temporal, intenta de nuevo en unos segundos."),
    DatabaseIntegrityError:  (409, "Ya existe un recurso con esos datos. Cambia los valores y vuelve a intentar."),
    # LLM
    LLMTimeoutError:        (504, "El modelo de IA está tardando más de lo esperado. Por favor, intenta de nuevo en unos segundos."),
    LLMRateLimitError:      (429, "Estás haciendo muchas solicitudes al modelo. Espera un minuto e intenta de nuevo."),
    LLMInvalidResponseError: (502, "El modelo de IA devolvió una respuesta inválida. Por favor, intenta de nuevo o cambia de modelo."),
    # File
    FileTooLargeError:      (413, None),  # detail filled at runtime from the exception message
    FileInvalidFormatError: (415, "El formato del archivo no es compatible. Usa PDF, Markdown o texto plano."),
    # RAG
    RAGEmbeddingError: (503, "No pudimos procesar tu consulta. Verifica tu conexión e intenta de nuevo."),
    # RAGSearchError lives in app.core.rag (not in app.core.exceptions) and
    # is handled locally by the RAG endpoints — the global handler does
    # not need it.
    # RAGSearchEmptyError is intentionally NOT mapped: the endpoint
    # converts it into a 200 with an empty results array (not a real
    # error).
}


@app.exception_handler(ArchAgentError)
async def _archagent_handler(_request, exc):
    """Single mapping from our typed errors to HTTP responses.

    Decorators in app/core/error_handlers.py keep working for the
    endpoints that still use them; the global handler is a backstop that
    also covers endpoints that were never decorated (F12 attachments, F13
    diagrams, etc.). The two layers must agree on status code + message; if
    they ever diverge, the global handler wins because the exception no longer
    reaches the per-endpoint decorator.

    Resolution order = MRO order: walk ``type(exc).__mro__`` from most
    specific to least specific and return the first registered class we
    find. This matches what users get when they register one handler per
    concrete class.
    """
    logger = logging.getLogger(__name__)

    for klass in type(exc).__mro__:
        if klass in _APP_AGENT_ERROR_MAPPING:
            status, generic = _APP_AGENT_ERROR_MAPPING[klass]
            detail = generic or str(exc)
            return JSONResponse(status_code=status, content={"detail": detail})

    # Fallback: unknown ArchAgentError
    logger.exception("Unhandled ArchAgentError: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Ocurrió un error inesperado. Intenta de nuevo."},
    )


# CORS — allow SPA frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Jinja register form (kept for backward compat during migration) ----------


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    return templates.TemplateResponse(
        request, "register.html", {"error": None, "success": False, "username": "", "email": ""}
    )


@app.post("/register", response_class=HTMLResponse)
async def register_submit(request: Request):
    form = await request.form()
    try:
        register_user(form["username"], form["email"], form["password"])
        return templates.TemplateResponse(
            request, "register.html", {"error": None, "success": True}
        )
    except ValidationError as e:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": str(e), "success": False,
                "username": form.get("username", ""), "email": form.get("email", ""),
            },
        )


# --- API routes --------------------------------------------------------------

from app.api.auth import router as auth_router
from app.api.projects import router as projects_router
from app.api.llm_config import router as llm_config_router
from app.api.documents import router as documents_router
from app.api.chat import router as chat_router
from app.api.users import router as users_router
from app.api.rag import router as rag_router
from app.api.patterns import router as patterns_router
from app.api.elicitation import router as elicitation_router
from app.api.attachments import router as attachments_router  # F13, issue #17
from app.api.diagrams import router as diagrams_router  # HU6: historial de diagramas
from app.api.proposals import router as proposals_router

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(llm_config_router)
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(users_router)
app.include_router(rag_router)
app.include_router(patterns_router)
app.include_router(elicitation_router)
app.include_router(attachments_router)
app.include_router(diagrams_router)
app.include_router(proposals_router)

# HU6: bundle de mermaid.js para el render server-side (sidecar de Puppeteer).
# Ruta puntual (no un StaticFiles de la raiz, que expondria server.py, .env...).
# Es una libreria publica; no requiere auth porque Chromium la pide sin token.
MERMAID_JS_FILE = Path(__file__).parent / "mermaid.min.js"


@app.get("/vendor/mermaid.min.js", include_in_schema=False)
async def vendor_mermaid_js():
    if not MERMAID_JS_FILE.is_file():
        raise HTTPException(status_code=404, detail="mermaid.min.js no disponible")
    return FileResponse(
        MERMAID_JS_FILE,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=86400"},
    )

# Serve SPA static files (built by Vite)
# Mount AFTER specific routes so /api/* and /register work first
SPA_DIST = Path(__file__).parent / "frontend" / "dist"
if SPA_DIST.exists():
    app.mount("/", StaticFiles(directory=str(SPA_DIST), html=True), name="spa")