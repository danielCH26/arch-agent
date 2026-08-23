## Cómo levantar el proyecto (hu 1)

### 1. Clonar y posicionarse en la rama `development`

```bash
git clone https://github.com/danielCH26/arch-agent.git
cd arch-agent
git checkout development
git pull origin development

```

### 2. Entorno de Python

```bash
python3 -m venv venv
source venv/bin/activate        # En Windows (PowerShell): venv\Scripts\Activate.ps1
pip install -r requirements.txt

```

### 3. Base de datos y servicios con Docker Compose

Inicia los contenedores en segundo plano:

```bash
docker compose up -d

```

Verifica que los servicios estén activos:

```bash
docker compose ps

```

Carga el esquema inicial de la base de datos:

* **En Windows (PowerShell):**
```powershell
Get-Content schema.sql | docker compose exec -T postgres-app psql -U asistente -d asistente_db

```


* **En Linux / macOS / CMD:**
```bash
docker compose exec -T postgres-app psql -U asistente -d asistente_db < schema.sql

```



### 4. Variables de entorno

Crea un archivo `.env` en la raíz con el siguiente parámetro:

```env
CHAINLIT_AUTH_SECRET=<pídeselo al equipo o genera uno con: chainlit create-secret>

```

### 5. Correr la app

```bash
uvicorn server:app --reload --port 8000

```

* **Registro:** `http://localhost:8000/register`
* **Chat / Login:** `http://localhost:8000/chainlit/login`

---

### Qué probar (criterios de aceptación de HU1)

* [ ] Crear una cuenta nueva en `/register` (username, email, password)
* [ ] Validaciones: password de menos de 8 caracteres, email con formato inválido, username o email ya usado — cada uno debe mostrar un mensaje claro sin borrar lo que ya escribiste
* [ ] Iniciar sesión en `/chainlit/` con la cuenta creada
* [ ] Recargar la página / cerrar y volver a abrir el navegador → debe seguir logueado (sesión persistida)
* [ ] Logout desde el menú del avatar → debe pedir credenciales de nuevo
* [ ] Entrar a `/chainlit/` en una ventana de incógnito, sin sesión → debe pedir login, no dejar pasar
* [ ] Probar comandos de perfil en el chat: `/perfil`, `/editar_perfil` y `/cambiar_password`
Cualquier bug o comportamiento raro, repórtalo como comentario en el PR o en el canal del equipo, indicando el paso exacto donde pasó.
