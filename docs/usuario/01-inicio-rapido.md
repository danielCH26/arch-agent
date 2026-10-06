# Guía de inicio rápido

De cero a tu primera propuesta de arquitectura en cinco pasos. Si quieres el detalle de cada pantalla, sigue con el [tutorial paso a paso](02-tutorial.md).

> **Antes de empezar:** Arch Agent tiene que estar corriendo. En una instalación local se levanta con `docker compose up -d` (ver el [README principal](../../README.md#quickstart)) y la app queda en **http://localhost:5173**.

---

## 1. Crea tu cuenta

1. Abre **http://localhost:5173**.
2. Haz clic en el enlace de registro.
3. Completa **usuario**, **email** y **contraseña** (mínimo 6 caracteres) y confirma la contraseña.
4. Al registrarte entras automáticamente al panel de proyectos.

#Screenshot-registro
<!-- Reemplazar por: ![Pantalla de registro](screenshots/registro.png) -->

## 2. Configurar tu LLM (obligatorio)

El agente necesita un modelo de lenguaje para funcionar. En la barra lateral, abajo, entra a **⚙️ Configuración LLM** y completa el asistente de 3 pasos:

| Paso | Qué ingresar | Ejemplo |
|------|--------------|---------|
| 1. Base URL | La URL del proveedor | `https://api.openai.com/v1` |
| 2. API Key | Tu clave del proveedor | `sk-...` |
| 3. Modelo | Elige uno de la lista | `gpt-4o` |

Prefiere los modelos con la etiqueta verde **"Recomendado"**.

#Screenshot-configuracion-llm
<!-- Reemplazar por: ![Asistente de configuración LLM](screenshots/configuracion-llm.png) -->

> Usas **Ollama** o **LM Studio** en tu máquina? Usa `http://host.docker.internal:11434/v1` (Ollama) o `http://host.docker.internal:1234/v1` (LM Studio) en lugar de `localhost`.

## 3. Crea un proyecto

1. Haz clic en **+ Nuevo proyecto** (barra lateral) o **Nuevo Proyecto** (panel principal).
2. Escribe un **nombre** y, opcionalmente, una **descripción** de la idea.
3. Haz clic en **Crear**: se abre el chat del proyecto en la fase **Requerimientos**.

#Screenshot-nuevo-proyecto
<!-- Reemplazar por: ![Diálogo de nuevo proyecto](screenshots/nuevo-proyecto.png) -->

## 4. Responde las preguntas del agente

El agente te hace preguntas una a una sobre el problema, los usuarios, las funcionalidades, las restricciones y los atributos de calidad. Responde en el cuadro de texto y presiona enviar.

Cuando tiene suficiente información, muestra un **resumen de requerimientos**. Revisalo y hace clic en **Aprobar** (o en **Modificar** para pedir ajustes). Después haz clic en **Continuar a Propuesta**.

#Screenshot-elicitacion
<!-- Reemplazar por: ![Chat de elicitación con resumen](screenshots/elicitacion.png) -->

## 5. Genera y aprueba la propuesta

1. En la fase **Propuesta**, haz clic en **Generar propuesta**.
2. Lee la arquitectura sugerida, los patrones citados y los trade-offs.
3. Haz clic en **Aprobar**, **Modificar** (para iterar con feedback) o **Rechazar**.
4. Con la propuesta aprobada, haz clic en **Continuar a Refinamiento**: el agente genera el **diagrama** automáticamente.

#Screenshot-propuesta
<!-- Reemplazar por: ![Tarjeta de propuesta de arquitectura](screenshots/propuesta.png) -->

¡Listo! Ya tienes una arquitectura documentada con su diagrama.

---

**Siguiente:** [Tutorial paso a paso](02-tutorial.md) · [FAQ](03-faq.md) · [Glosario](04-glosario.md)