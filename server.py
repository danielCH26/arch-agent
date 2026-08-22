from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from chainlit.utils import mount_chainlit
from fastapi.templating import Jinja2Templates
from app.auth.register import register_user
from app.auth.validators import ValidationError
from dotenv import load_dotenv
load_dotenv()

templates = Jinja2Templates(directory="templates")  
app = FastAPI()

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
# Monta el chat de Chainlit (app.py) como sub-app, bajo /chainlit.
# Todo lo que Chainlit registre internamente (incluida su ruta atrapa-todo)
# queda confinado a ese prefijo y no puede tapar las rutas de arriba.
mount_chainlit(app=app, target="app.py", path="/chainlit")