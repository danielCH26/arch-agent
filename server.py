from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from chainlit.utils import mount_chainlit
from app.auth.register import register_user
from app.auth.validators import ValidationError
from dotenv import load_dotenv
load_dotenv()

app = FastAPI()

@app.get("/register", response_class=HTMLResponse)
async def register_form():
    return """
    <h2>Crear cuenta</h2>
    <form method="post" action="/register">
      <input name="username" placeholder="username"><br>
      <input name="email" placeholder="email"><br>
      <input name="password" type="password" placeholder="password (mín. 8)"><br>
      <button type="submit">Crear cuenta</button>
    </form>
    """

@app.post("/register", response_class=HTMLResponse)
async def register_submit(request: Request):
    form = await request.form()
    try:
        register_user(form["username"], form["email"], form["password"])
        return "<p>Cuenta creada. <a href='/chainlit'>Ir a iniciar sesión</a></p>"
    except ValidationError as e:
        return f"<p>Error: {e}</p><a href='/register'>Volver a intentar</a>"

# Monta el chat de Chainlit (app.py) como sub-app, bajo /chainlit.
# Todo lo que Chainlit registre internamente (incluida su ruta atrapa-todo)
# queda confinado a ese prefijo y no puede tapar las rutas de arriba.
mount_chainlit(app=app, target="app.py", path="/chainlit")