# Tutorial paso a paso

Este tutorial recorre Arch Agent de punta a punta con un proyecto de ejemplo: **"TurnoFácil"**, una app para que clínicas pequeñas gestionen turnos de pacientes. Si es tu primera vez, conviene leer antes la [guía de inicio rápido](01-inicio-rapido.md).

## Índice

1. [Registro e inicio de sesión](#1-registro-e-inicio-de-sesión)
2. [Conocer la interfaz](#2-conocer-la-interfaz)
3. [Configurar el LLM](#3-configurar-el-llm)
4. [Crear un proyecto](#4-crear-un-proyecto)
5. [Subir documentos de contexto](#5-subir-documentos-de-contexto)
6. [Fase 1 — Requerimientos (elicitación)](#6-fase-1--requerimientos-elicitación)
7. [Fase 2 — Propuesta de arquitectura](#7-fase-2--propuesta-de-arquitectura)
8. [Fase 3 — Refinamiento (diagrama)](#8-fase-3--refinamiento-diagrama)
9. [Fase 4 — Revisión](#9-fase-4--revisión)
10. [Historial de diagramas](#10-historial-de-diagramas)
11. [Perfil y cuenta](#11-perfil-y-cuenta)

---

## 1. Registro e inicio de sesión

### Crear una cuenta

1. Abre la app (por defecto **http://localhost:5173**) y entra a la pantalla de registro.
2. Completa:
   - **Usuario** — tu nombre de usuario para iniciar sesión.
   - **Email** — una dirección válida.
   - **Contraseña** — mínimo 6 caracteres. Usa el ícono del ojo para mostrarla u ocultarla.
   - **Confirmar contraseña** — tiene que coincidir.
3. Envia el formulario. Si todo es válido, entras directamente al panel de proyectos.

#Screenshot-registro
<!-- Reemplazar por: ![Pantalla de registro](screenshots/registro.png) -->

### Iniciar sesión

En visitas posteriores ingresa tu **usuario** y **contraseña** en la pantalla de inicio de sesión. La sesión dura un tiempo limitado (por defecto 60 minutos); cuando expira, la app te devuelve al login.

#Screenshot-inicio-sesion
<!-- Reemplazar por: ![Pantalla de inicio de sesión](screenshots/inicio-sesion.png) -->

---

## 2. Conocer la interfaz

#Screenshot-página-principal
<!-- Reemplazar por: ![Página principal con barra lateral y lista de proyectos](screenshots/pagina-principal.png) -->

| Zona | Qué contiene |
|------|--------------|
| **Encabezado** | Logo *Arch Agent* (vuelve a la lista de proyectos), tu nombre de usuario y **Cerrar sesión**. |
| **Barra lateral — Proyectos** | Tus proyectos. Al hacer clic en uno se despliegan sus secciones **💬 Chat** y **📄 Documentos**. Abajo, el botón **+ Nuevo proyecto**. |
| **Barra lateral — pie** | **👤 Perfil** y **⚙️ Configuración LLM**. |
| **Área principal** | La pantalla activa: lista de proyectos, chat, documentos o configuración. |

> En pantallas angostas (celular) la barra lateral se oculta; usa el panel principal de **Proyectos** para navegar.

---

## 3. Configurar el LLM

Arch Agent no trae un modelo propio: **cada usuario conecta el suyo**. Sin este paso el agente no puede responder.

Entra a **⚙️ Configuración LLM**. El asistente tiene tres pasos:

### Paso 1 — Base URL

Pega la URL base del proveedor. El asistente verifica que la URL responda como una API compatible con OpenAI.

| Proveedor | Base URL |
|-----------|----------|
| OpenAI | `https://api.openai.com/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| Together AI | `https://api.together.xyz/v1` |
| Ollama (local) | `http://host.docker.internal:11434/v1` |
| LM Studio (local) | `http://host.docker.internal:1234/v1` |

#Screenshot-llm-paso1-base-url
<!-- Reemplazar por: ![Paso 1: Base URL](screenshots/llm-paso1-base-url.png) -->

### Paso 2 — API Key

Pega la clave del proveedor. El asistente prueba la conexión real. La clave **se guarda cifrada** y solo cuando confirmas el paso 3; después nunca se vuelve a mostrar completa.

#Screenshot-llm-paso2-api-key
<!-- Reemplazar por: ![Paso 2: API Key](screenshots/llm-paso2-api-key.png) -->

### Paso 3 — Modelo

Elige el modelo de la lista desplegable. Los modelos están clasificados por calidad (puntaje **MMLU**):

| Etiqueta | Significado | ¿Se puede elegir? |
|----------|-------------|-------------------|
| 🟢 **Recomendado** (Tier 1) | MMLU ≥ 85 | Sí, directamente. |
| 🟡 **Sin score conocido** | MMLU entre 60 y 85, o desconocido | Sí, pero pide confirmación. |
| *(no aparece)* | MMLU < 60 | No: se bloquea por baja calidad. |

¿Tu modelo no está en la lista (por ejemplo, un fine-tune)? Usa **Cancelar** en este paso para que aparezca un campo de texto y escribe el nombre exacto del modelo. Haz clic en **Guardar**.

#Screenshot-llm-paso3-modelo
<!-- Reemplazar por: ![Paso 3: selección de modelo](screenshots/llm-paso3-modelo.png) -->

### Cambiar la configuración más adelante

Si ya tienes una configuración guardada, verás un **resumen** con dos opciones:

- **Cambiar modelo** — salta directo al paso 3 manteniendo URL y clave.
- **Cambiar todo** — vuelve al paso 1.

#Screenshot-llm-resumen
<!-- Reemplazar por: ![Resumen de configuración LLM](screenshots/llm-resumen.png) -->

---

## 4. Crear un proyecto

1. Haz clic en **+ Nuevo proyecto**.
2. **Nombre** (obligatorio): `TurnoFácil`.
3. **Descripción** (opcional, pero ayuda al agente): `App web para que clínicas pequeñas gestionen turnos, recordatorios y cancelaciones de pacientes.`
4. Haz clic en **Crear**.

La app abre el **chat** del proyecto, en la fase **Requerimientos**. El nombre del proyecto y su fase actual se ven en la parte superior del chat.

#Screenshot-nuevo-proyecto
<!-- Reemplazar por: ![Diálogo de nuevo proyecto](screenshots/nuevo-proyecto.png) -->

En la lista de **Proyectos** cada tarjeta muestra el nombre, la descripción y una **etiqueta de fase** (con ✓ cuando la fase actual ya está aprobada).

#Screenshot-lista-proyectos
<!-- Reemplazar por: ![Lista de proyectos con etiquetas de fase](screenshots/lista-proyectos.png) -->

---

## 5. Subir documentos de contexto

Si ya tienes material (actas de reunión, notas, especificaciones), subelo para que el agente lo tenga en cuenta.

- **Formatos:** PDF (`.pdf`) y Markdown (`.md`).
- **Tamaño máximo:** 10 MB por archivo.

Hay dos formas de subirlos:

1. **Desde 📄 Documentos** (barra lateral, dentro del proyecto): arrastra el archivo a la zona punteada o haz clic para elegirlo. Ahí también ves la lista de documentos y puedes eliminarlos.
2. **Desde el chat**: con el botón de adjuntar junto al cuadro de texto. Funciona incluso cuando el texto está bloqueado esperando que apruebes el resumen.

Si subes un archivo con un nombre que ya existe, la app te pregunta qué hacer:

| Opción | Resultado |
|--------|-----------|
| **Reemplazar** | Sube una nueva versión que reemplaza a la anterior. |
| **Subir con sufijo** | Guarda el archivo como uno nuevo, con un sufijo en el nombre. |
| **Cancelar** | No sube nada. |

#Screenshot-documentos
<!-- Reemplazar por: ![Pantalla de documentos del proyecto](screenshots/documentos.png) -->

#Screenshot-archivo-duplicado
<!-- Reemplazar por: ![Diálogo de archivo duplicado](screenshots/archivo-duplicado.png) -->

> **Tip:** si subes un documento nuevo después de que el agente ya generó el resumen de requerimientos, usa **Modificar** en el resumen para que lo incorpore.

---

## 6. Fase 1 — Requerimientos (elicitación)

El objetivo de esta fase es que el agente entienda **qué** hay que construir. Lo hace con preguntas progresivas, una por vez.

### Responder las preguntas

Al entrar al chat el agente ya te muestra la primera pregunta. Responde en el cuadro **"Escribe un mensaje..."** y envia. Ejemplo de conversación:

> **Agente:** ¿Qué problema resuelve el sistema y para quién?
>
> **Vos:** Las clínicas chicas manejan los turnos por teléfono y planillas; se pierden turnos y hay muchas ausencias. Lo usarían recepcionistas, médicos y pacientes.
>
> **Agente:** ¿Cuáles son las funcionalidades indispensables?
>
> **Vos:** Reservar y cancelar turnos online, agenda por profesional, recordatorios por email/WhatsApp y un panel de ausencias.

Mientras el agente piensa verás tres puntos animados. Responde con el mayor detalle posible: volumen esperado de usuarios, presupuesto, tecnologías obligatorias o prohibidas, requisitos de disponibilidad o seguridad, etc.

#Screenshot-elicitacion
<!-- Reemplazar por: ![Chat de elicitación](screenshots/elicitacion.png) -->

### Validar el resumen

Cuando el agente tiene suficiente información, muestra un **Resumen de requerimientos para validar** con:

- **Problema** y **Usuarios**
- **Funcionalidades**
- **Restricciones**
- **Calidad** (atributos de calidad: rendimiento, disponibilidad, seguridad…)

Debajo aparece la pregunta *"¿El resumen representa las necesidades del proyecto?"* con tres botones:

| Botón | Qué hace |
|-------|----------|
| **Aprobar** | Da por buenos los requerimientos. La fase queda lista para avanzar. |
| **Modificar** | Abre un campo *"¿Qué debe ajustarse?"*. Describe el cambio y haz clic en **Enviar ajuste**; el agente regenera el resumen. |
| **Rechazar** | Descarta el resumen y reinicia la elicitación desde cero. |

#Screenshot-resumen-requerimientos
<!-- Reemplazar por: ![Resumen de requerimientos con botones de decisión](screenshots/resumen-requerimientos.png) -->

### Avanzar de fase

Al aprobar aparece un aviso verde: **"Requerimientos aprobados ✓ Ya puedes continuar a la fase de Propuesta"**. Haz clic en **Continuar a Propuesta**. Si antes de avanzar te acuerdas de algo, usa **Pedir un ajuste**.

#Screenshot-avanzar-fase
<!-- Reemplazar por: ![Aviso de fase aprobada con botón Continuar](screenshots/avanzar-fase.png) -->

---

## 7. Fase 2 — Propuesta de arquitectura

En esta fase el agente propone **cómo** construirlo, apoyándose en su base de conocimiento de patrones de arquitectura (capas, hexagonal, microservicios, monolito modular, event-driven, CQRS, serverless, etc.).

### Generar la propuesta

En la tarjeta **Propuesta de arquitectura** haz clic en **Generar propuesta**. El texto aparece a medida que se genera (*streaming*). La propuesta incluye normalmente:

- Estilo/patrón de arquitectura recomendado y su justificación.
- Componentes principales y sus responsabilidades.
- **Tabla de trade-offs** comparando alternativas.
- **Citas** a los patrones de la base de conocimiento que respaldan la decisión.

La etiqueta en la esquina de la tarjeta indica el estado: **Propuesta**, **Aprobada** o **Rechazada**.

#Screenshot-propuesta
<!-- Reemplazar por: ![Tarjeta de propuesta con trade-offs y citas](screenshots/propuesta.png) -->

### Decidir sobre la propuesta

Debajo de la propuesta tenés:

| Control | Qué hace |
|---------|----------|
| **Aprobar** | Acepta la propuesta y habilita el avance a Refinamiento. |
| **Modificar** | Abre un cuadro para escribir feedback (ej.: *"agregar caché con Redis"*, *"usar PostgreSQL en vez de MongoDB"*). Haz clic en **Iterar propuesta** para generar una nueva versión. |
| **Rechazar** | Descarta la propuesta. |
| **Comentario** (opcional) | Nota breve que queda registrada junto con tu decisión de aprobar o rechazar. |

Mientras se genera una nueva iteración, **la versión actual se conserva** en pantalla. Cada iteración muestra arriba el feedback que la originó.

#Screenshot-iterar-propuesta
<!-- Reemplazar por: ![Cuadro de feedback para iterar la propuesta](screenshots/iterar-propuesta.png) -->

### Evolución del diseño

Cuando hay más de una versión aparece la sección desplegable **"Evolución del diseño (N versiones)"**, donde puedes releer cada iteración anterior y el feedback que la produjo.

#Screenshot-evolucion-diseno
<!-- Reemplazar por: ![Historial de iteraciones de la propuesta](screenshots/evolucion-diseno.png) -->

Con la propuesta aprobada, haz clic en **Continuar a Refinamiento**.

---

## 8. Fase 3 — Refinamiento (diagrama)

Al entrar a esta fase **el agente genera automáticamente el diagrama** de la propuesta aprobada (en formato Mermaid, renderizado como imagen). No hace falta pedirlo.

#Screenshot-diagrama
<!-- Reemplazar por: ![Diagrama generado en el chat](screenshots/diagrama.png) -->

### Ver el diagrama en grande

Haz clic sobre la miniatura para abrir el **visor ampliado**. Usa los botones de **acercar** / **alejar** para ajustar el zoom y cerralo cuando termines.

#Screenshot-visor-diagrama
<!-- Reemplazar por: ![Visor ampliado del diagrama con zoom](screenshots/visor-diagrama.png) -->

### Decidir sobre el diagrama

Cada diagrama del chat tiene sus propios botones:

| Botón | Qué hace |
|-------|----------|
| **✅ Aprobar** | Registra el diagrama como aprobado. |
| **❌ Rechazar** | Lo marca como rechazado. |
| **✏️ Solicitar cambios** | Abre *"¿Qué debe ajustarse en el diagrama?"*; el agente modifica el diagrama existente según tu pedido (no lo rehace desde cero). |

También puedes seguir conversando con el agente en el chat para hacerle preguntas sobre la arquitectura o pedir aclaraciones.

Cuando la fase está aprobada aparece **Continuar a Revisión**.

---

## 9. Fase 4 — Revisión

Es la última fase del flujo. Por ahora no tiene una pantalla propia: el chat sigue disponible para consultar al agente sobre la arquitectura final, y en la lista de proyectos el proyecto aparece con la etiqueta **Revisión**.

#Screenshot-revision
<!-- Reemplazar por: ![Proyecto en fase de Revisión](screenshots/revision.png) -->

---

## 10. Historial de diagramas

En la parte superior del chat, el botón **🕘 Historial de diagramas** abre un panel lateral con todas las versiones de diagramas del proyecto y su estado:

- ✅ **Aprobado**
- ❌ **Rechazado**
- ✏️ **Cambios solicitados**
- **Sin decisión**

El panel es **solo de consulta**: las decisiones se toman en el chat, sobre cada diagrama.

#Screenshot-historial-diagramas
<!-- Reemplazar por: ![Panel de historial de diagramas](screenshots/historial-diagramas.png) -->

---

## 11. Perfil y cuenta

En **👤 Perfil** puedes:

- Ver y editar tu **usuario** y **email** (guarda con **Guardar cambios**), y ver la fecha de **Miembro desde**.
- **Cambiar la contraseña**: ingresa la actual y la nueva (mínimo **8** caracteres).

Para salir, usa **Cerrar sesión** en el encabezado.

#Screenshot-perfil
<!-- Reemplazar por: ![Pantalla de perfil de usuario](screenshots/perfil.png) -->

---

**Siguiente:** [FAQ](03-faq.md) · [Glosario](04-glosario.md) · [Volver al índice](README.md)