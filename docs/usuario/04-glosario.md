# Glosario de términos

Términos que aparecen en Arch Agent y en esta documentación, ordenados alfabéticamente dentro de cada grupo.

## Fases

| Término | Definición |
|---------|------------|
| **Fase** | Cada etapa del flujo de trabajo de un proyecto. Se avanza de una a la siguiente solo cuando la actual está aprobada. |
| **Requerimientos** | Fase 1. El agente hace preguntas (elicitación) y arma un resumen de lo que hay que construir. |
| **Propuesta** | Fase 2. El agente propone una arquitectura justificada, con patrones y trade-offs. |
| **Refinamiento** | Fase 3. Se genera y ajusta el diagrama de la propuesta aprobada. |
| **Revisión** | Fase 4 y última. Consulta final de la arquitectura. |
| **Fase lista (✓)** | Indica que la fase actual fue aprobada y se puede avanzar. |

## Conceptos de la app

| Término | Definición |
|---------|------------|
| **Agente** | El asistente de IA de Arch Agent que conversa con vos, hace preguntas y genera propuestas y diagramas. |
| **Base de conocimiento** | Colección de patrones de arquitectura documentados que el agente consulta para fundamentar sus propuestas. |
| **Cita** | Referencia, dentro de una propuesta, al patrón de la base de conocimiento que respalda una decisión. |
| **Documento de contexto** | Archivo PDF o Markdown que subes a un proyecto para que el agente lo tenga en cuenta. |
| **Elicitación** | Proceso de descubrir los requerimientos mediante preguntas progresivas. |
| **Evolución del diseño** | Historial de todas las iteraciones de una propuesta, con el feedback que originó cada una. |
| **Historial de diagramas** | Panel que lista todas las versiones de diagramas de un proyecto y su estado. Es solo de consulta. |
| **Iteración** | Nueva versión de una propuesta generada a partir de tu feedback (botón **Modificar**). |
| **Proyecto** | Espacio de trabajo para una idea de producto: contiene la conversación, los documentos, las propuestas y los diagramas. |
| **Resumen de requerimientos** | Síntesis que genera el agente al final de la elicitación: problema, usuarios, funcionalidades, restricciones y calidad. |
| **Streaming** | Forma en que se muestran las respuestas: el texto aparece a medida que el modelo lo genera. |
| **Sufijo (subir con)** | Opción ante un archivo duplicado: guarda el nuevo archivo con otro nombre en lugar de reemplazar el existente. |
| **Versión (de documento)** | Número que identifica cada reemplazo de un mismo archivo (v1, v2…). |

## Requerimientos

| Término | Definición |
|---------|------------|
| **Atributo de calidad** | Característica no funcional que el sistema debe cumplir: rendimiento, disponibilidad, seguridad, escalabilidad, mantenibilidad, etc. Aparece como **Calidad** en el resumen. |
| **Funcionalidad** | Algo concreto que el sistema debe permitir hacer (ej.: "reservar un turno"). |
| **Requerimiento** | Necesidad o condición que el sistema debe satisfacer. |
| **Restricción** | Límite impuesto al diseño: presupuesto, plazos, tecnologías obligatorias o prohibidas, normativas. |

## Arquitectura

| Término | Definición |
|---------|------------|
| **API Gateway / BFF** | Punto de entrada único que enruta las solicitudes a los servicios internos; el *Backend For Frontend* es una variante adaptada a cada tipo de cliente. |
| **Arquitectura de software** | Estructura de alto nivel de un sistema: sus componentes, cómo se relacionan y las decisiones que la justifican. |
| **Arquitectura en capas** | Organiza el sistema en capas (presentación, negocio, datos) donde cada una solo depende de la inferior. |
| **Arquitectura hexagonal** | También "puertos y adaptadores": el núcleo de negocio queda aislado de la infraestructura mediante interfaces. |
| **Clean Architecture** | Variante que organiza el código en círculos concéntricos, con las reglas de negocio en el centro y sin dependencias hacia afuera. |
| **Componente** | Parte del sistema con una responsabilidad clara (ej.: servicio de notificaciones, base de datos). |
| **CQRS** | *Command Query Responsibility Segregation*: separa el modelo de escritura (comandos) del de lectura (consultas). |
| **Event-driven** | Arquitectura orientada a eventos: los componentes se comunican publicando y consumiendo eventos de forma asíncrona. |
| **Event Sourcing** | Guarda el estado como la secuencia de eventos que lo produjeron, en lugar de solo el estado actual. |
| **Microservicios** | El sistema se divide en servicios pequeños, desplegables de forma independiente, cada uno con su propia responsabilidad. |
| **Monolito modular** | Una sola aplicación desplegable, dividida internamente en módulos bien separados. |
| **Patrón de arquitectura** | Solución probada y reutilizable para un problema recurrente de diseño. |
| **Serverless** | Modelo en el que el código corre como funciones gestionadas por un proveedor cloud, sin administrar servidores. |
| **Trade-off** | Compromiso entre alternativas: lo que se gana y lo que se pierde al elegir una opción frente a otra. |

## Diagramas

| Término | Definición |
|---------|------------|
| **Diagrama de arquitectura** | Representación visual de los componentes y sus relaciones. |
| **Mermaid** | Lenguaje de texto con el que el agente describe los diagramas; la app lo convierte en imagen. |
| **Visor ampliado** | Ventana que se abre al hacer clic en un diagrama, con controles de zoom. |

## LLM y configuración

| Término | Definición |
|---------|------------|
| **API compatible con OpenAI** | Interfaz estándar que ofrecen muchos proveedores; Arch Agent puede usar cualquiera que la implemente. |
| **API Key** | Clave secreta que te da el proveedor para autenticar las solicitudes. Se guarda cifrada. |
| **Base URL** | Dirección base de la API del proveedor (ej.: `https://api.openai.com/v1`). |
| **LLM** | *Large Language Model*: modelo de lenguaje de gran escala (GPT-4o, Claude, Llama, Qwen…) que impulsa al agente. |
| **MMLU** | Benchmark que mide el conocimiento general de un modelo. Arch Agent lo usa para clasificar los modelos por calidad. |
| **Modelo local** | LLM que corre en tu propia máquina (con Ollama o LM Studio), sin enviar datos a terceros. |
| **Modo degradado** | Respuesta reducida que da la app cuando el modelo no pudo completar una acción (ej.: no soporta tool calling). |
| **Proveedor** | Servicio que ofrece el LLM (OpenAI, OpenRouter, Groq, Ollama…). |
| **Tier** | Nivel de calidad asignado a un modelo según su MMLU: **Tier 1 / Recomendado** (≥ 85), **Sin score conocido** (60–85 o desconocido) y bloqueado (< 60). |
| **Tool calling** | Capacidad de un modelo de invocar herramientas externas de forma estructurada. Necesaria para generar diagramas. |

---

[Volver al índice](README.md)