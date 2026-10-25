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
Al menos 8 caracteres, con una letra mayúscula, un número y un carácter especial (por ejemplo `! @ # $ % &`). La regla es la misma al registrarte y al cambiarla desde tu perfil.

**La app me devolvió al login sin que yo cerrara sesión.**
Tu sesión expiró (por defecto dura 60 minutos). Vuelve a iniciar sesión; tus proyectos y conversaciones se conservan.

**Olvidé mi contraseña.**
Por ahora no hay recuperación automática por email. Pídele al administrador de tu instalación que te ayude a restablecerla.

**Veo "Ese proyecto ya no está disponible para tu usuario".**
El proyecto no existe o pertenece a otro usuario. Cada usuario solo ve sus propios proyectos.

---

## Configuración del LLM

**¿Por qué tengo que configurar un LLM?**
Arch Agent no incluye un modelo propio: usa el proveedor que tú elijas. Sin configuración, el agente no puede hacer preguntas ni generar propuestas.

**¿Qué proveedores puedo usar?**
Cualquiera compatible con la API de OpenAI: OpenAI, OpenRouter, Groq, DeepSeek, Together AI, vLLM, y modelos locales con Ollama o LM Studio. Ver la tabla del [tutorial](02-tutorial.md#3-configurar-el-llm).

**Uso Ollama en mi PC y el paso 1 (URL base) falla.**
Si Arch Agent corre en Docker, `localhost` apunta al contenedor, no a tu PC. Usa `http://host.docker.internal:11434/v1` (o el puerto `1234` para LM Studio) y verifica que Ollama esté corriendo.

**El paso 2 dice que la API key no es válida.**
Revisa que la copiaste completa, sin espacios, que corresponde al mismo proveedor que la URL del paso 1 y que la cuenta tiene saldo o cuota disponible.

**No encuentro mi modelo en la lista.**
Puede pasar por dos motivos:
- Tiene un puntaje MMLU menor a 60 y está bloqueado por baja calidad (por ejemplo, `gpt-3.5-turbo`).
- Es un modelo personalizado que el proveedor no lista. En ese caso, haz clic en **No encuentro mi modelo — escribir manualmente** en el paso 3 y escribe el nombre exacto.

**¿Qué significa "Sin score conocido"?**
El modelo no tiene un puntaje de calidad registrado o está entre 60 y 85 de MMLU. Puedes usarlo, pero los resultados pueden ser peores que con un modelo del grupo **Recomendados (Tier 1)**.

**Los diagramas no se generan.**
La generación del diagrama necesita un modelo con buen soporte de *tool calling*. Modelos como `llama3` (Llama 3.0) no lo tienen. Cambia a uno con buen soporte de *tool calling*, como `gpt-4o`, `gpt-4o-mini`, `claude-sonnet-4`, `qwen2.5-coder` o `llama-3.1` en adelante.

**Debajo del diagrama aparece un aviso.**
La app avisa cuando el diagrama no se pudo convertir en imagen o cuando incluye componentes que no están respaldados por la documentación consultada. Puedes pedirle al agente que lo vuelva a generar o usar **✏️ Solicitar cambios**.

**Aparece un error del proveedor (por ejemplo, 429) en medio de la elicitación.**
El proveedor está limitando las solicitudes o no tienes cuota. Espera unos segundos y usa **Reintentar**. Tus respuestas anteriores no se pierden.

---

## Proyectos y fases

**¿Cuáles son las fases y en qué orden van?**
Requerimientos → Propuesta → Refinamiento → Revisión → Cierre. Ver el [glosario](04-glosario.md#fases).

**¿Puedo saltarme una fase?**
No. Solo se avanza cuando la fase actual está aprobada. En Requerimientos y Propuesta la fase queda lista al aprobar el resumen o la propuesta; en Refinamiento, Revisión y Cierre, con **Aprobar** en el panel de decisión del chat. Si después rechazas, la fase vuelve a quedar pendiente.

**¿Qué significa "Lista para avanzar" en la tarjeta de un proyecto?**
Que la fase actual ya fue aprobada y el proyecto puede avanzar a la siguiente. Si dice **En progreso**, la fase todavía no está lista. Con **Continuar** retomas el proyecto.

**No puedo escribir en el chat durante la elicitación.**
Cuando el agente muestra el resumen de requerimientos, el cuadro de respuesta desaparece hasta que decidas con **Aprobar**, **Solicitar cambios** o **Rechazar y reiniciar**. Si quieres sumar un documento, súbelo desde **Documentos** y luego usa **Solicitar cambios**.

**¿Qué diferencia hay entre "Solicitar cambios" y "Rechazar y reiniciar" en el resumen?**
**Solicitar cambios** conserva lo conversado y ajusta el resumen según tu pedido. **Rechazar y reiniciar** descarta el resumen y reinicia la elicitación desde cero.

**Cerré el navegador en medio de un proyecto. ¿Pierdo lo que hice?**
No. Al volver a abrir el proyecto se recupera la conversación, el resumen, la propuesta vigente y los diagramas.

---

## Documentos

**¿Qué archivos puedo subir?**
PDF (`.pdf`) y Markdown (`.md`), de hasta 10 MB cada uno.

**¿Para qué sirven los documentos?**
El agente los usa como contexto adicional: por ejemplo, actas de reunión, notas del cliente o especificaciones existentes.

**Subí un documento después de que el agente generó el resumen. ¿Lo tiene en cuenta?**
Usa **Solicitar cambios** en el resumen (por ejemplo: *"incorpora lo del acta que acabo de subir"*) para que se regenere con el nuevo documento.

**Me aparece "Archivo duplicado".**
Ya existe un archivo con ese nombre en el proyecto. Elige **Reemplazar** (nueva versión), **Subir con sufijo** (archivo aparte) o **Cancelar**.

---

## Propuestas y diagramas

**Hice clic en "Avanzar fase →" y la propuesta no aparece.**
La propuesta se genera a pedido: haz clic en **Generar propuesta** dentro de la tarjeta.

**La generación de la propuesta falló.**
Se muestra el error en la tarjeta y el botón **Generar propuesta** vuelve a estar disponible para reintentar.

**¿Cuántas veces puedo iterar una propuesta?**
Hasta el máximo de iteraciones configurado en tu instalación. Al alcanzarlo, la app te pide que apruebes o rechaces la propuesta. La tarjeta muestra siempre la iteración más reciente.

**Rechacé la propuesta y volví a Requerimientos. ¿Por qué?**
**Rechazar** una propuesta devuelve el proyecto a la fase Requerimientos, porque se interpreta que el problema está en los requerimientos. Si solo quieres ajustar la propuesta, usa **Modificar**.

**¿De dónde salen los patrones que cita la propuesta?**
De la **Base de patrones** de Arch Agent (puedes consultarla desde la barra lateral) (capas, hexagonal, clean architecture, monolito modular, microservicios, event-driven, event sourcing, CQRS, API Gateway/BFF, serverless). Las citas te permiten ver en qué se apoya cada decisión.

**¿Tengo que pedir el diagrama?**
Sí. Al entrar a **Refinamiento** escríbele al agente en el chat, por ejemplo: *"Genera el diagrama de la propuesta aprobada"*.

**¿Puedo aprobar o rechazar diagramas desde el Historial de diagramas?**
No, el historial (botón **Diagramas**) es solo de consulta. Las decisiones se toman sobre cada diagrama en el chat.

**El diagrama se ve muy chico.**
Haz clic sobre él para abrir el visor ampliado y usa los controles **−** y **+**. También puedes usar **Abrir original** para verlo en una pestaña nueva.

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