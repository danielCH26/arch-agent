# Capturas de pantalla

Esta carpeta contiene las capturas usadas en la documentación de usuario.

## Cómo agregar una captura

1. Saca la captura de la app corriendo (ancho recomendado: **1280 px**, formato **PNG**).
2. Guardala en esta carpeta con el **nombre de archivo** de la tabla.
3. En el documento, reemplaza la línea `#Screenshot-...` y el comentario HTML que tiene debajo por la imagen. Por ejemplo:

   ```markdown
   #Screenshot-página-principal
   <!-- Reemplazar por: ![Página principal de Arch Agent](screenshots/pagina-principal.png) -->
   ```

   pasa a ser:

   ```markdown
   ![Página principal de Arch Agent](screenshots/pagina-principal.png)
   ```

   > Desde el `README.md` raíz la ruta es `docs/usuario/screenshots/<archivo>.png`.

4. No incluyas datos reales (API keys, emails personales, documentos confidenciales) en las capturas.

## Capturas pendientes

| Marcador | Archivo | Qué mostrar | Usado en |
|----------|---------|-------------|----------|
| `#Screenshot-página-principal` | `pagina-principal.png` | Barra lateral + lista de proyectos | README raíz, [README](../README.md), [Tutorial §2](../02-tutorial.md#2-conocer-la-interfaz) |
| `#Screenshot-registro` | `registro.png` | Formulario de registro | [Inicio rápido](../01-inicio-rapido.md), [Tutorial §1](../02-tutorial.md#1-registro-e-inicio-de-sesión) |
| `#Screenshot-inicio-sesion` | `inicio-sesion.png` | Formulario de login | [Tutorial §1](../02-tutorial.md#1-registro-e-inicio-de-sesión) |
| `#Screenshot-configuracion-llm` | `configuracion-llm.png` | Asistente de configuración LLM | [Inicio rápido](../01-inicio-rapido.md) |
| `#Screenshot-llm-paso1-base-url` | `llm-paso1-base-url.png` | Paso 1 del asistente | [Tutorial §3](../02-tutorial.md#3-configurar-el-llm) |
| `#Screenshot-llm-paso2-api-key` | `llm-paso2-api-key.png` | Paso 2 del asistente (key oculta) | [Tutorial §3](../02-tutorial.md#3-configurar-el-llm) |
| `#Screenshot-llm-paso3-modelo` | `llm-paso3-modelo.png` | Paso 3 con el desplegable de modelos y tiers | [Tutorial §3](../02-tutorial.md#3-configurar-el-llm) |
| `#Screenshot-llm-resumen` | `llm-resumen.png` | Vista resumen con "Cambiar modelo" / "Cambiar todo" | [Tutorial §3](../02-tutorial.md#3-configurar-el-llm) |
| `#Screenshot-nuevo-proyecto` | `nuevo-proyecto.png` | Diálogo "Nuevo Proyecto" | [Inicio rápido](../01-inicio-rapido.md), [Tutorial §4](../02-tutorial.md#4-crear-un-proyecto) |
| `#Screenshot-lista-proyectos` | `lista-proyectos.png` | Tarjetas de proyectos con etiquetas de fase | [Tutorial §4](../02-tutorial.md#4-crear-un-proyecto) |
| `#Screenshot-documentos` | `documentos.png` | Zona de carga + lista de documentos | [Tutorial §5](../02-tutorial.md#5-subir-documentos-de-contexto) |
| `#Screenshot-archivo-duplicado` | `archivo-duplicado.png` | Diálogo "Archivo duplicado" | [Tutorial §5](../02-tutorial.md#5-subir-documentos-de-contexto) |
| `#Screenshot-elicitacion` | `elicitacion.png` | Chat con preguntas y respuestas | README raíz, [Inicio rápido](../01-inicio-rapido.md), [Tutorial §6](../02-tutorial.md#6-fase-1--requerimientos-elicitación) |
| `#Screenshot-resumen-requerimientos` | `resumen-requerimientos.png` | Resumen + botones Aprobar/Modificar/Rechazar | [Tutorial §6](../02-tutorial.md#6-fase-1--requerimientos-elicitación) |
| `#Screenshot-avanzar-fase` | `avanzar-fase.png` | Aviso verde con "Continuar a …" | [Tutorial §6](../02-tutorial.md#6-fase-1--requerimientos-elicitación) |
| `#Screenshot-propuesta` | `propuesta.png` | Tarjeta de propuesta con trade-offs y citas | README raíz, [Inicio rápido](../01-inicio-rapido.md), [Tutorial §7](../02-tutorial.md#7-fase-2--propuesta-de-arquitectura) |
| `#Screenshot-iterar-propuesta` | `iterar-propuesta.png` | Cuadro de feedback abierto ("Iterar propuesta") | [Tutorial §7](../02-tutorial.md#7-fase-2--propuesta-de-arquitectura) |
| `#Screenshot-evolucion-diseno` | `evolucion-diseno.png` | Sección "Evolución del diseño" desplegada | [Tutorial §7](../02-tutorial.md#7-fase-2--propuesta-de-arquitectura) |
| `#Screenshot-diagrama` | `diagrama.png` | Diagrama en el chat con sus botones | README raíz, [Tutorial §8](../02-tutorial.md#8-fase-3--refinamiento-diagrama) |
| `#Screenshot-visor-diagrama` | `visor-diagrama.png` | Visor ampliado con zoom | [Tutorial §8](../02-tutorial.md#8-fase-3--refinamiento-diagrama) |
| `#Screenshot-revision` | `revision.png` | Proyecto en fase Revisión | [Tutorial §9](../02-tutorial.md#9-fase-4--revisión) |
| `#Screenshot-historial-diagramas` | `historial-diagramas.png` | Panel lateral de historial | [Tutorial §10](../02-tutorial.md#10-historial-de-diagramas) |
| `#Screenshot-perfil` | `perfil.png` | Pantalla "Mi Perfil" | [Tutorial §11](../02-tutorial.md#11-perfil-y-cuenta) |

> Los mockups originales de diseño están en [`mockups-UI/`](../../../mockups-UI/README.md); sirven de referencia pero **no** reemplazan a capturas de la app real.
