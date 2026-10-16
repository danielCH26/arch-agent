# Capturas de pantalla

Esta carpeta contiene las capturas usadas en la documentación de usuario. Todas están tomadas de la interfaz de la rama `development`.

## Cómo agregar o reemplazar una captura

1. Saca la captura de la app corriendo (ancho recomendado: **1280 px**, formato **PNG**).
2. Guárdala en esta carpeta con un nombre en **minúsculas, sin tildes ni eñes y con guiones** (por ejemplo `evolucion-diseno.png`). GitHub distingue mayúsculas de minúsculas en las rutas.
3. Referénciala desde el documento con la ruta relativa:

   ```markdown
   ![Página principal de Arch Agent](screenshots/pagina-principal.png)
   ```

   > Desde el `README.md` raíz la ruta es `docs/usuario/screenshots/<archivo>.png`.

4. Agrega o actualiza la fila correspondiente en la tabla de abajo.
5. No incluyas datos reales (API keys, emails personales, documentos confidenciales) en las capturas.

## Capturas en uso

| Archivo | Qué muestra | Usado en |
|---------|-------------|----------|
| `pagina-principal.png` | Barra lateral + **Mis proyectos** | README raíz, [README](../README.md), [Tutorial §2](../02-tutorial.md#2-conocer-la-interfaz) |
| `registro.png` | Formulario de registro | [Inicio rápido §1](../01-inicio-rapido.md), [Tutorial §1](../02-tutorial.md#1-registro-e-inicio-de-sesión) |
| `inicio-sesion.png` | Formulario de inicio de sesión | [Tutorial §1](../02-tutorial.md#1-registro-e-inicio-de-sesión) |
| `llm-paso1-base-url.png` | Paso 1 del asistente LLM (URL base) | [Tutorial §3](../02-tutorial.md#3-configurar-el-llm) |
| `llm-paso2-api-key.png` | Paso 2 del asistente LLM (key oculta) | [Tutorial §3](../02-tutorial.md#3-configurar-el-llm) |
| `configuracion-llm.png` | Paso 3 del asistente LLM, con el desplegable de modelos | [Inicio rápido §2](../01-inicio-rapido.md), [Tutorial §3](../02-tutorial.md#3-configurar-el-llm) |
| `llm-resumen.png` | **Tu configuración actual** con "Cambiar modelo" / "Cambiar todo" | [Tutorial §3](../02-tutorial.md#3-configurar-el-llm) |
| `nuevo-proyecto.png` | Diálogo **Nuevo proyecto** vacío | [Inicio rápido §3](../01-inicio-rapido.md) |
| `nuevo-proyecto-turnofacil.png` | Diálogo **Nuevo proyecto** con los datos de TurnoFácil | [Tutorial §4](../02-tutorial.md#4-crear-un-proyecto) |
| `lista-proyectos.png` | Tarjetas de proyectos con fase y estado | [Tutorial §4](../02-tutorial.md#4-crear-un-proyecto) |
| `documentos.png` | **Subida de archivos** + **Documentos subidos** | [Tutorial §5](../02-tutorial.md#5-subir-documentos-de-contexto) |
| `archivo-duplicado.png` | Diálogo **Archivo duplicado** | [Tutorial §5](../02-tutorial.md#5-subir-documentos-de-contexto) |
| `elicitacion.png` | Chat de elicitación con preguntas y respuestas | README raíz, [Tutorial §6](../02-tutorial.md#6-fase-1--requerimientos-elicitación) |
| `chat-elicitacion-resumen.png` | Chat de elicitación con el resumen | [Inicio rápido §4](../01-inicio-rapido.md) |
| `resumen-requerimientos-turnofacil.png` | **Resumen del proyecto** con "¿Apruebas este resumen?" | [Tutorial §6](../02-tutorial.md#6-fase-1--requerimientos-elicitación) |
| `avanzar-fase.png` | "✓ Resumen aprobado" y **Avanzar fase →** | [Tutorial §6](../02-tutorial.md#6-fase-1--requerimientos-elicitación) |
| `propuesta.png` | Tarjeta **Propuesta de arquitectura** | README raíz, [Inicio rápido §5](../01-inicio-rapido.md), [Tutorial §7](../02-tutorial.md#7-fase-2--propuesta-de-arquitectura) |
| `feedback-propuesta.png` | Cuadro **"¿Qué debería cambiar?"** con **Generar nueva iteración** | [Tutorial §7](../02-tutorial.md#7-fase-2--propuesta-de-arquitectura) |
| `iterar-propuesta.png` | "Generando nueva iteración..." con el ajuste solicitado | [Tutorial §7](../02-tutorial.md#7-fase-2--propuesta-de-arquitectura) |
| `iterar-propuesta-2.png` | Iteración 2 con el ajuste solicitado y "Pendiente de decisión" | [Tutorial §7](../02-tutorial.md#7-fase-2--propuesta-de-arquitectura) |
| `evolucion-diseno.png` | Aviso "N iteraciones generadas en esta sesión…" | [Tutorial §7](../02-tutorial.md#7-fase-2--propuesta-de-arquitectura) |
| `diagrama.png` | Diagrama en el chat con sus botones | README raíz, [Tutorial §8](../02-tutorial.md#8-fase-3--refinamiento-diagrama) |
| `visor-diagrama.png` | Visor ampliado con sus controles | [Tutorial §8](../02-tutorial.md#8-fase-3--refinamiento-diagrama) |
| `revision.png` | Chat del proyecto en fase Revisión | [Tutorial §9](../02-tutorial.md#9-fase-4--revisión) |
| `revision-2.png` | **Mis proyectos** con el proyecto en Revisión | [Tutorial §9](../02-tutorial.md#9-fase-4--revisión) |
| `perfil.png` | Pantalla de perfil | [Tutorial §11](../02-tutorial.md#11-perfil-y-cuenta) |

## Capturas sin uso (pendientes de recaptura)

| Archivo | Problema | Qué debería mostrar |
|---------|----------|---------------------|
| `historial-diagramas.png` | Muestra solo la barra lateral, sin el panel. | El panel **Historial de diagramas** abierto (botón **Diagramas**), para [Tutorial §10](../02-tutorial.md#10-historial-de-diagramas). |
| `propuesta-arquitectura.png` | Es un diagrama, no la tarjeta de propuesta. | Se puede borrar o reutilizar como ejemplo de diagrama en [Tutorial §8](../02-tutorial.md#8-fase-3--refinamiento-diagrama). |

En total hay **28** capturas: 26 en uso y 2 pendientes.

> Los mockups originales de diseño están en [`mockups-UI/`](../../../mockups-UI/README.md); sirven de referencia pero **no** reemplazan a capturas de la app real.
