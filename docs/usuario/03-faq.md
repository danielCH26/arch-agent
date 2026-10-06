# Preguntas frecuentes (FAQ)

## Índice

- [Cuenta y acceso](#cuenta-y-acceso)
- [Configuración del LLM](#configuración-del-llm)
- [Proyectos y fases](#proyectos-y-fases)
- [Documentos](#documentos)
- [Propuestas y diagramas](#propuestas-y-diagramas)
- [Privacidad y datos](#privacidad-y-datos)

---

## Cuenta y acceso

**¿Qué requisitos tiene la contraseña?**
Al registrarte, mínimo 6 caracteres. Al cambiarla desde **Perfil**, mínimo 8 caracteres.

**La app me devolvió al login sin que yo cerrara sesión.**
Tu sesión expiró (por defecto dura 60 minutos). Vuelve a iniciar sesión; tus proyectos y conversaciones se conservan.

**Olvidé mi contraseña.**
Por ahora no hay recuperación automática por email. Pidele al administrador de tu instalación que te ayude a restablecerla.

**Veo "Ese proyecto ya no está disponible para tu usuario".**
El proyecto no existe o pertenece a otro usuario. Cada usuario solo ve sus propios proyectos.

---

## Configuración del LLM

**¿Por qué tengo que configurar un LLM?**
Arch Agent no incluye un modelo propio: usa el proveedor que vos elijas. Sin configuración, el agente no puede hacer preguntas ni generar propuestas.

**¿Qué proveedores puedo usar?**
Cualquiera compatible con la API de OpenAI: OpenAI, OpenRouter, Groq, DeepSeek, Together AI, vLLM, y modelos locales con Ollama o LM Studio. Ver la tabla del [tutorial](02-tutorial.md#3-configurar-el-llm).

**Uso Ollama en mi PC y el paso 1 falla.**
Si Arch Agent corre en Docker, `localhost` apunta al contenedor, no a tu PC. Usa `http://host.docker.internal:11434/v1` (o el puerto `1234` para LM Studio) y verifica que Ollama esté corriendo.

**El paso 2 dice que la API key no es válida.**
Revisa que la copiaste completa, sin espacios, que corresponde al mismo proveedor que la URL del paso 1 y que la cuenta tiene saldo o cuota disponible.

**No encuentro mi modelo en la lista.**
Puede pasar por dos motivos:
- Tiene un puntaje MMLU menor a 60 y está bloqueado por baja calidad (por ejemplo, `gpt-3.5-turbo`).
- Es un modelo personalizado que el proveedor no lista. En ese caso, usa **Cancelar** en el paso 3 y escribe el nombre exacto a mano.

**¿Qué significa "Sin score conocido"?**
El modelo no tiene un puntaje de calidad registrado o está entre 60 y 85 de MMLU. Puedes usarlo, pero los resultados pueden ser peores; por eso la app te pide confirmación.

**Los diagramas no se generan o veo un aviso de "modo degradado".**
La generación del diagrama necesita un modelo con buen soporte de *tool calling*. Modelos como `llama3` (Llama 3.0) no lo tienen. Cambia a uno recomendado: `gpt-4o`, `gpt-4o-mini`, `claude-sonnet-4`, `qwen2.5-coder` o `llama-3.1`+.

**Aparece un error del proveedor (por ejemplo, 429) en medio de la elicitación.**
El proveedor está limitando las solicitudes o no tienes cuota. Espera unos segundos y usa **Reintentar**. Tus respuestas anteriores no se pierden.

---

## Proyectos y fases

**¿Cuáles son las fases y en qué orden van?**
Requerimientos → Propuesta → Refinamiento → Revisión. Ver el [glosario](04-glosario.md#fases).

**¿Puedo saltear una fase?**
No. Cada fase tiene que estar aprobada para que aparezca el botón **Continuar a …**.

**¿Qué significa el ✓ en la etiqueta de fase de un proyecto?**
Que la fase actual ya fue aprobada y el proyecto está listo para avanzar a la siguiente.

**No puedo escribir en el chat durante la elicitación.**
Cuando el agente muestra el resumen de requerimientos, el cuadro de texto se bloquea hasta que decidas con **Aprobar**, **Modificar** o **Rechazar**. Sí puedes seguir adjuntando documentos.

**¿Qué diferencia hay entre "Modificar" y "Rechazar" en el resumen?**
**Modificar** conserva lo conversado y ajusta el resumen según tu pedido. **Rechazar** descarta el resumen y reinicia la elicitación.

**Cerré el navegador en medio de un proyecto. ¿Pierdo lo que hice?**
No. Al volver a abrir el proyecto se recupera la conversación, el resumen, la propuesta vigente y los diagramas.

---

## Documentos

**¿Qué archivos puedo subir?**
PDF (`.pdf`) y Markdown (`.md`), de hasta 10 MB cada uno.

**¿Para qué sirven los documentos?**
El agente los usa como contexto adicional: por ejemplo, actas de reunión, notas del cliente o especificaciones existentes.

**Subí un documento después de que el agente generó el resumen. ¿Lo tiene en cuenta?**
Usa **Modificar** en el resumen (por ejemplo: *"incorporá lo del acta que acabo de subir"*) para que se regenere con el nuevo documento.

**Me aparece "Archivo duplicado".**
Ya existe un archivo con ese nombre en el proyecto. Elige **Reemplazar** (nueva versión), **Subir con sufijo** (archivo aparte) o **Cancelar**.

---

## Propuestas y diagramas

**Hice clic en "Continuar a Propuesta" y no aparece nada.**
La propuesta se genera a pedido: haz clic en **Generar propuesta** dentro de la tarjeta.

**La generación de la propuesta falló.**
Se muestra el error en la tarjeta y el botón **Generar propuesta** vuelve a estar disponible para reintentar.

**¿Cuántas veces puedo iterar una propuesta?**
Las que necesites. Cada iteración queda guardada en **Evolución del diseño**.

**¿De dónde salen los patrones que cita la propuesta?**
De la base de conocimiento de patrones de Arch Agent (capas, hexagonal, clean architecture, monolito modular, microservicios, event-driven, event sourcing, CQRS, API Gateway/BFF, serverless). Las citas te permiten ver en qué se apoya cada decisión.

**¿Tengo que pedir el diagrama?**
No. Al entrar a **Refinamiento** se genera solo. Si vuelves a entrar y ya existe un diagrama, no se regenera.

**¿Puedo aprobar o rechazar diagramas desde el Historial de diagramas?**
No, el historial es solo de consulta. Las decisiones se toman sobre cada diagrama en el chat.

**El diagrama se ve muy chico.**
Haz clic sobre él para abrir el visor ampliado y usa los controles de zoom.

---

## Privacidad y datos

**¿Dónde se guarda mi API key?**
En la base de datos de tu instalación de Arch Agent, **cifrada**. La interfaz nunca la vuelve a mostrar completa.

**¿Mis conversaciones se envían a algún lado?**
Tus mensajes y documentos se envían al proveedor de LLM que configuraste para que pueda responder. Si quieres que nada salga de tu máquina, usa un modelo local (Ollama o LM Studio).

**¿Otros usuarios pueden ver mis proyectos?**
No. Cada proyecto pertenece a su usuario.

---

¿No encontraste tu respuesta? Revisa el [tutorial](02-tutorial.md) o consulta al administrador de tu instalación.