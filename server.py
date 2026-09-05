from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv

from app.auth.register import register_user
from app.auth.validators import ValidationError

load_dotenv()

templates = Jinja2Templates(directory="templates")
app = FastAPI(title="Arch Agent API", version="1.0.0")

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

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(llm_config_router)
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(users_router)
app.include_router(rag_router)
app.include_router(patterns_router)

# Serve SPA static files (built by Vite)
# Mount AFTER specific routes so /api/* and /register work first
SPA_DIST = Path(__file__).parent / "frontend" / "dist"
if SPA_DIST.exists():
    app.mount("/", StaticFiles(directory=str(SPA_DIST), html=True), name="spa")
