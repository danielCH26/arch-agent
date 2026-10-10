"""Plantillas de diagrama Mermaid por patron principal.

El DIAGRAM_HINT de ``app/core/agent.py`` trae tres plantillas fijas (capas,
hexagonal, orientada a eventos). Este modulo cubre los 19 patrones del
catalogo (data/patterns/*.yaml) y elige UNA sola plantilla segun el patron
principal de la propuesta aprobada, para que el prompt del turno de diagrama
no crezca con 19 plantillas que no aplican.

Cada plantilla resume la forma canonica que muestran las fuentes del patron
(ver docs/DIAGRAMAS_POR_PATRON.md). Son esqueletos, no diagramas cerrados:
el modelo debe usar solo los componentes que nombra la propuesta. La
observabilidad, el API Gateway, el broker y los nodos de despliegue NO forman
parte de ninguna plantilla: solo se dibujan si la propuesta los incluye.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class DiagramTemplate:
    key: str
    label: str
    keywords: tuple[str, ...]
    skeleton: str


# El orden importa solo para desempatar dos coincidencias en la misma
# posicion del texto: la palabra clave mas larga gana (ver _find_principal).
DIAGRAM_TEMPLATES: tuple[DiagramTemplate, ...] = (
    DiagramTemplate(
        "layered",
        "Arquitectura en capas",
        ("arquitectura en capas", "en capas", "por capas", "layered", "n-tier", "n capas", "tres capas"),
        "`flowchart TB`: Cliente --> Presentacion --> Aplicacion/Negocio --> "
        "Acceso a datos --> Base de datos. Cada capa depende solo de la "
        "inmediatamente inferior; no dibujes flechas que salten capas ni "
        "flechas hacia arriba.",
    ),
    DiagramTemplate(
        "hexagonal",
        "Arquitectura hexagonal",
        ("hexagonal", "puertos y adaptadores", "ports and adapters"),
        "`flowchart LR` con tres subgraphs: `Adaptadores de entrada` (API REST, "
        "UI, CLI) --> `Nucleo de dominio` (puertos de entrada, casos de uso, "
        "dominio, puertos de salida) --> `Adaptadores de salida` (repositorio, "
        "cliente externo) --> infraestructura. El dominio no apunta a ningun "
        "adaptador.",
    ),
    DiagramTemplate(
        "clean",
        "Clean Architecture",
        ("clean architecture", "arquitectura limpia", "onion"),
        "`flowchart LR` con subgraphs concentricos de afuera hacia adentro: "
        "`Frameworks e infraestructura` (web, BD) --> `Adaptadores de interfaz` "
        "(controladores, presentadores, repositorios) --> `Casos de uso` --> "
        "`Entidades`. Todas las flechas apuntan hacia adentro; la "
        "infraestructura implementa interfaces del nucleo (flecha punteada "
        "`-.implementa.->`).",
    ),
    DiagramTemplate(
        "modular_monolith",
        "Monolito modular",
        ("monolito modular", "modular monolith"),
        "`flowchart TB`: Cliente --> un subgraph `Aplicacion (un despliegue)` "
        "con un subgraph por modulo de dominio, cada uno con su interfaz "
        "publica; los modulos se llaman solo por esa interfaz (flecha "
        "etiquetada `API interna`). Una sola Base de datos, con un esquema por "
        "modulo si la propuesta lo menciona. Sin red entre modulos.",
    ),
    DiagramTemplate(
        "microservices",
        "Microservicios",
        ("microservicios", "microservices"),
        "`flowchart LR`: Cliente --> (API Gateway solo si la propuesta lo "
        "incluye) --> un nodo por servicio de dominio; cada servicio --> su "
        "propia base de datos (nunca una BD compartida). Comunicacion entre "
        "servicios: flecha solida para HTTP sincrono y punteada `-.evento.->` "
        "hacia un broker solo si la propuesta lo incluye.",
    ),
    DiagramTemplate(
        "api_gateway_bff",
        "API Gateway + BFF",
        ("backend for frontend", "backends for frontends", "bff", "api gateway"),
        "`flowchart LR`: un nodo por tipo de cliente (Web, Movil) --> su BFF "
        "(BFF Web, BFF Movil) --> servicios o API de backend --> datos. Si hay "
        "un solo cliente y un despliegue, dibuja el BFF como una capa de API "
        "dentro de la aplicacion, no como servicio separado.",
    ),
    DiagramTemplate(
        "event_driven",
        "Orientada a eventos",
        ("orientada a eventos", "event-driven", "event driven", "basada en eventos"),
        "`flowchart LR`: Productores -.evento.-> Broker/Bus de eventos "
        "-.evento.-> Consumidores independientes. Etiqueta cada flecha "
        "asincrona con el nombre del evento de la propuesta; la cola de "
        "mensajes fallidos (DLQ) solo si la propuesta la menciona.",
    ),
    DiagramTemplate(
        "cqrs",
        "CQRS",
        ("cqrs", "command query responsibility segregation"),
        "`flowchart LR` con dos caminos desde el Cliente: `Comandos` --> "
        "Manejadores de comandos --> Modelo de escritura (BD); `Consultas` --> "
        "Manejadores de consultas --> Modelo de lectura. Sincronizacion "
        "escritura -.proyeccion.-> lectura. En la version minima ambos modelos "
        "viven en la misma base de datos: dibuja una sola BD.",
    ),
    DiagramTemplate(
        "event_sourcing",
        "Event sourcing",
        ("event sourcing", "event-sourcing"),
        "`flowchart LR`: Comando --> Agregado --> Almacen de eventos (solo "
        "agrega) -.eventos.-> Proyecciones --> Modelo de lectura <-- Consultas. "
        "Si la propuesta usa una tabla de eventos en la BD principal, dibuja "
        "esa tabla en lugar de un almacen dedicado.",
    ),
    DiagramTemplate(
        "saga",
        "Saga",
        ("saga",),
        "`flowchart LR` con orquestacion: Orquestador de saga --> Paso 1 "
        "(servicio A) --> Paso 2 (servicio B) --> Paso 3; para cada paso una "
        "flecha punteada `-.compensa.->` con su accion de compensacion. Con "
        "coreografia, reemplaza el orquestador por eventos entre servicios.",
    ),
    DiagramTemplate(
        "serverless",
        "Serverless",
        ("serverless", "function-as-a-service", "function as a service", "faas"),
        "`flowchart LR`: Cliente --> punto de entrada HTTP gestionado --> una "
        "funcion por responsabilidad --> servicios gestionados (BD, "
        "almacenamiento de objetos). Disparadores no HTTP (cola, cron, "
        "evento de almacenamiento) como nodos de entrada con flecha punteada.",
    ),
    DiagramTemplate(
        "soa",
        "SOA",
        ("orientada a servicios", "service-oriented", "soa"),
        "`flowchart LR`: Aplicaciones consumidoras --> Capa de integracion "
        "(ESB o API corporativa) --> Servicios de negocio reutilizables --> "
        "sistemas existentes (ERP, CRM, legado). Registro de servicios solo si "
        "la propuesta lo incluye.",
    ),
    DiagramTemplate(
        "microkernel",
        "Microkernel",
        ("microkernel", "plugins", "plug-in", "plugin"),
        "`flowchart TB`: Nucleo (reglas comunes) --> Contrato de extension; "
        "cada Plugin --> Contrato de extension. Los plugins no se conectan "
        "entre si ni con el nucleo directamente.",
    ),
    DiagramTemplate(
        "mvc_mvvm",
        "MVC / MVVM",
        ("mvvm", "mvc", "modelo-vista-controlador", "model-view-controller"),
        "`flowchart LR`: Usuario --> Vista --> Controlador (MVC) o ViewModel "
        "(MVVM) --> Modelo --> almacenamiento; Modelo/ViewModel -.notifica.-> "
        "Vista. La Vista nunca apunta al almacenamiento.",
    ),
    DiagramTemplate(
        "pipes_filters",
        "Pipes and Filters",
        ("pipes and filters", "tuberias y filtros", "pipe-and-filter"),
        "`flowchart LR`: Fuente --> Filtro 1 --> Filtro 2 --> ... --> Destino, "
        "en el orden real de la propuesta. Etiqueta cada tuberia con el dato "
        "que transporta; los filtros no comparten estado.",
    ),
    DiagramTemplate(
        "etl",
        "Pipeline ETL / ELT",
        ("etl", "elt", "extract, transform"),
        "`flowchart LR`: Fuentes de datos --> Extraccion --> Staging --> "
        "Transformacion y validacion de calidad --> Carga --> Almacen "
        "analitico --> Reportes/BI. Orquestador -.programa.-> cada etapa. "
        "En ELT la transformacion va dentro del almacen analitico.",
    ),
    DiagramTemplate(
        "lambda_kappa",
        "Lambda / Kappa",
        ("lambda / kappa", "arquitectura lambda", "arquitectura kappa", "kappa", "lambda"),
        "Kappa (preferida con equipo pequeno): `flowchart LR` Fuentes --> Log de "
        "eventos --> Procesador de streaming --> Capa de servicio --> Consumo, "
        "con Log -.reproceso.-> Procesador. Lambda: Ingesta --> Capa batch "
        "--> Vistas batch y Ingesta --> Capa de velocidad --> Vistas en tiempo "
        "real; ambas --> Capa de servicio --> Consultas.",
    ),
    DiagramTemplate(
        "medallion",
        "Lakehouse Medallion",
        ("medallion", "lakehouse", "bronce", "bronze"),
        "`flowchart LR`: Fuentes --> Bronce (crudo) --> Plata (limpio y "
        "conformado) --> Oro (listo para consumo) --> BI / ciencia de datos. "
        "Etiqueta cada flecha con la transformacion entre capas.",
    ),
    DiagramTemplate(
        "mlops",
        "Pipeline de MLOps",
        ("mlops", "machine learning operations"),
        "`flowchart LR`: Datos --> Preparacion/features --> Entrenamiento --> "
        "Evaluacion --> Registro de modelos --> Serving (API o lotes) --> "
        "Monitoreo; Monitoreo -.reentrenar.-> Entrenamiento solo si la "
        "propuesta automatiza el reentrenamiento.",
    ),
)

_TEMPLATES_BY_KEY = {template.key: template for template in DIAGRAM_TEMPLATES}

# Seccion de la propuesta donde se declara el patron principal.
_SECTION_PATTERN = re.compile(
    r"^#{1,6}\s*patrones\s*$(?P<body>.*?)(?=^#{1,6}\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_PRINCIPAL_LINE = re.compile(r"^.*principal.*$", re.IGNORECASE | re.MULTILINE)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def _keyword_regex(keyword: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(_normalize(keyword))}(?![a-z0-9])")


_KEYWORD_PATTERNS: tuple[tuple[re.Pattern[str], int, DiagramTemplate], ...] = tuple(
    (_keyword_regex(keyword), len(keyword), template)
    for template in DIAGRAM_TEMPLATES
    for keyword in template.keywords
)


def _find_principal(text: str) -> DiagramTemplate | None:
    """Plantilla cuya palabra clave aparece primero en ``text``.

    A igual posicion gana la palabra clave mas larga ("event sourcing" antes
    que un "eventos" suelto, "lambda / kappa" antes que "lambda").
    """
    normalized = _normalize(text)
    best: tuple[int, int, DiagramTemplate] | None = None
    for pattern, length, template in _KEYWORD_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        candidate = (match.start(), -length, template)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best[2] if best else None


def template_for_pattern_name(pattern_name: str | None) -> DiagramTemplate | None:
    if not pattern_name:
        return None
    return _find_principal(pattern_name)


def template_for_proposal(proposal_text: str | None) -> DiagramTemplate | None:
    """Detecta el patron principal en el texto de una propuesta aprobada.

    Orden de busqueda: una linea de la seccion ``## Patrones`` que diga
    "principal"; si no, la primera mencion dentro de esa seccion; si la
    propuesta no tiene esa seccion, la primera mencion en todo el texto.
    """
    if not proposal_text:
        return None
    section = _SECTION_PATTERN.search(proposal_text)
    if section is not None:
        body = section.group("body")
        for line in _PRINCIPAL_LINE.findall(body):
            found = _find_principal(line)
            if found is not None:
                return found
        found = _find_principal(body)
        if found is not None:
            return found
    return _find_principal(proposal_text)


def _metadata(doc: Any) -> dict:
    metadata = getattr(doc, "metadata", None)
    if metadata is None and isinstance(doc, dict):
        metadata = doc.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _page(doc: Any) -> str:
    page = getattr(doc, "page_content", "")
    if not page and isinstance(doc, dict):
        page = doc.get("page_content", "")
    return str(page or "")


def select_diagram_template(rag_documents: Iterable[Any] | None) -> DiagramTemplate | None:
    """Plantilla del patron principal para el turno de diagrama.

    Solo usa la propuesta aprobada (``source_type == "approved_proposal"``):
    es la fuente de verdad del diagrama. Sin propuesta aprobada no se elige
    plantilla, para no imponer la forma de un patron que el usuario no
    aprobo.
    """
    for doc in rag_documents or []:
        if _metadata(doc).get("source_type") == "approved_proposal":
            return template_for_proposal(_page(doc))
    return None


def render_template_hint(template: DiagramTemplate | None) -> str:
    if template is None:
        return ""
    return (
        f"PLANTILLA DEL PATRON PRINCIPAL APROBADO ({template.label}): "
        f"{template.skeleton} Usa solo los componentes que nombra la propuesta "
        "aprobada; si la plantilla menciona un nodo que la propuesta no "
        "incluye, omitelo. Conecta cada servicio externo desde el componente "
        "que lo usa segun la propuesta (por ejemplo Notificaciones --> "
        "servicio de correo), no desde el punto de entrada; si hay un "
        "planificador o tareas programadas, conectalo con el modulo que "
        "ejecuta la tarea. Si la propuesta nombra alternativas ('X/Y'), "
        "dibuja solo la primera."
    )


def get_template(key: str) -> DiagramTemplate:
    return _TEMPLATES_BY_KEY[key]
