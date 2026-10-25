"""Preocupaciones transversales que suelen decidir la arquitectura.

Problema: el sistema no sabía qué suele ser decisivo en un dominio. Que una
app de mascotas perdidas necesita mapas, o que una clínica guarda datos
sensibles, dependía de que el LLM se acordara. Si no lo hacía, la propuesta y
el ADR salían sin esa pieza y nadie lo notaba.

Este módulo revisa, sin LLM, una lista corta de preocupaciones que aparecen en
casi cualquier dominio: ubicación, archivos o imágenes, datos personales,
notificaciones o tiempo real, pagos, integraciones y respaldos. Para cada una:

* ``relevante``: el texto del proyecto o su dominio la sugieren (``triggers``,
  ``domains``) o el usuario ya la nombró (``covered``). ``always`` = aplica a
  todo sistema que guarde datos.
* ``cubierta``: el usuario la mencionó de forma explícita (``covered``).

Una preocupación relevante y no cubierta se convierte en una pregunta de
elicitación (``question``) y, si llega sin respuesta al ADR, en una pregunta
abierta obligatoria de la sección 7.8 (``open_question``).

Todo se compara sobre texto sin acentos y en minúsculas, con límites de
palabra, igual que los factores de viabilidad de la elicitación.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from app.core.text_norm import normalize_text


@dataclass(frozen=True)
class DomainConcern:
    key: str
    label: str
    covered: tuple[str, ...]
    triggers: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    always: bool = False
    # Pregunta de elicitación: UNA sola dimensión (Issue #100).
    question: str = ""
    # Pregunta abierta para la sección 7.8 del ADR.
    open_question: str = ""


DOMAIN_CONCERNS: tuple[DomainConcern, ...] = (
    DomainConcern(
        key="ubicacion",
        label="Ubicación y mapas",
        covered=(
            r"mapas?", r"geoloc\w*", r"gps", r"ubicaci\w+", r"coordenadas",
            r"georreferenc\w*", r"geograf\w+",
        ),
        triggers=(
            r"perdid\w*", r"extraviad\w*", r"cercan\w+", r"domicili\w*",
            r"repartidor\w*", r"rutas?", r"rastre\w*", r"flota", r"viajes?",
            r"inmobiliari\w*", r"sucursal\w*",
        ),
        domains=("logistica", "transporte", "turismo", "inmobiliari", "movilidad"),
        question="¿El sistema necesita mostrar ubicaciones en un mapa o buscar por cercanía?",
        open_question=(
            "¿Se necesitan mapas o búsqueda por cercanía? Si es así, falta elegir "
            "el proveedor de mapas y revisar su costo por uso."
        ),
    ),
    DomainConcern(
        key="archivos",
        label="Archivos e imágenes",
        covered=(
            r"fotos?", r"fotografias?", r"imagen(?:es)?", r"archivos?", r"adjunt\w+",
            r"pdfs?", r"videos?", r"almacenamiento\s+de\s+\w+",
        ),
        triggers=(
            r"publicaci\w+", r"anuncios?", r"evidencias?", r"historia\s+clinica",
            r"catalogo", r"mascotas?", r"galeria", r"expedientes?", r"comprobantes?",
        ),
        question="¿Los usuarios van a subir fotos, documentos u otros archivos al sistema?",
        open_question=(
            "¿Se van a subir fotos o archivos? Falta definir dónde se guardan "
            "(almacenamiento de objetos o disco), el tamaño máximo y quién puede verlos."
        ),
    ),
    DomainConcern(
        key="datos_personales",
        label="Datos personales",
        covered=(
            r"datos\s+personales", r"privacidad", r"habeas\s+data", r"ley\s+1581",
            r"gdpr", r"consentimiento", r"anonimiz\w+", r"datos\s+sensibles",
            r"confidencial\w*",
        ),
        triggers=(
            r"pacientes?", r"historias?\s+clinicas?", r"menores", r"cedulas?",
            r"documento\s+de\s+identidad", r"salarios?", r"nominas?",
            r"datos\s+de\s+contacto", r"telefonos?",
        ),
        domains=("salud", "finanzas", "educacion", "recursos humanos", "banca", "aseguradora"),
        question="¿Qué datos personales o sensibles va a guardar el sistema?",
        open_question=(
            "¿Qué datos personales se guardan y qué norma de protección de datos "
            "aplica? Define quién puede consultarlos y cómo se protegen."
        ),
    ),
    DomainConcern(
        key="notificaciones",
        label="Notificaciones y tiempo real",
        covered=(
            r"notificaci\w+", r"alertas?", r"avisos?", r"recordatorios?", r"push",
            r"sms", r"whatsapp", r"tiempo\s+real", r"websockets?", r"correos?\s+automatic\w+",
        ),
        triggers=(
            r"citas?", r"reservas?", r"turnos?", r"pedidos?", r"chat", r"mensajeria",
            r"emergenci\w+", r"perdid\w*", r"seguimiento",
        ),
        question="¿El sistema debe avisar a los usuarios por correo, notificación push o SMS?",
        open_question=(
            "¿Hay que notificar a los usuarios (correo, push, SMS) o mostrar cambios "
            "en tiempo real? Falta definir el canal y el proveedor."
        ),
    ),
    DomainConcern(
        key="pagos",
        label="Pagos",
        covered=(
            r"pagos?", r"cobros?", r"pasarelas?", r"tarjetas?\s+de\s+credito",
            r"factur\w+", r"suscripci\w+", r"paypal", r"stripe", r"mercado\s*pago",
            r"wompi", r"pse",
        ),
        triggers=(
            r"tienda", r"tienda\s+en\s+linea", r"e-?commerce", r"carrito",
            r"membresi\w+", r"donaci\w+", r"tarifas?", r"mensualidad\w*",
        ),
        domains=("e-commerce", "comercio", "finanzas", "retail"),
        question="¿El sistema va a recibir pagos en línea?",
        open_question=(
            "¿Se cobran pagos en línea? Si es así, falta elegir la pasarela y "
            "confirmar que el sistema no guarde datos de tarjetas."
        ),
    ),
    DomainConcern(
        key="integraciones",
        label="Integraciones con otros sistemas",
        covered=(
            r"integra\w+", r"apis?\s+extern\w+", r"erp", r"crm", r"sistemas?\s+existentes?",
            r"sincroniz\w+", r"webhooks?", r"importar", r"exportar",
        ),
        triggers=(
            r"eps", r"bancos?", r"sap", r"odoo", r"siigo", r"proveedores?",
            r"sistema\s+actual", r"legado", r"legacy",
        ),
        question="¿El sistema debe conectarse con otros sistemas o servicios externos?",
        open_question=(
            "¿Con qué sistemas externos hay que integrarse? Falta confirmar si "
            "tienen API y quién la mantiene."
        ),
    ),
    # Las tres siguientes salieron de la prueba del observatorio de analítica:
    # la elicitación nunca preguntó si había datos de menores, cuánto se
    # guardaban los eventos ni cada cuánto debía estar al día el tablero, y la
    # propuesta quedó con la tensión lotes / tiempo real sin resolver.
    DomainConcern(
        key="frescura",
        label="Frescura de los datos",
        covered=(
            r"tiempo\s+real", r"en\s+vivo", r"cada\s+(?:minuto|hora|dia|noche|semana|mes)",
            r"diari\w+", r"semanal\w*", r"actualiza\w*\s+(?:cada|en|al|diari\w*|semanal\w*)",
            r"al\s+dia", r"near\s+real\s+time", r"refresco",
        ),
        triggers=(
            r"tableros?", r"dashboards?", r"indicadores?", r"reportes?", r"analitica",
            r"power\s*bi", r"metricas?", r"monitoreo", r"ocupacion",
        ),
        question="¿Cada cuánto deben estar actualizados los datos que se muestran (en tiempo real, cada hora o cada día)?",
        open_question=(
            "¿Cada cuánto deben estar al día los datos de cada tablero o reporte? "
            "Si alguno necesita tiempo real, la arquitectura debe tener una vía "
            "aparte de la carga por lotes."
        ),
    ),
    DomainConcern(
        key="menores",
        label="Datos de menores de edad",
        covered=(
            r"menores\s+de\s+edad", r"menores", r"ninos", r"ninas", r"adolescentes",
            r"mayores\s+de\s+edad", r"acudientes?", r"padres\s+de\s+familia",
        ),
        triggers=(
            r"estudiantes?", r"alumnos?", r"colegios?", r"escuelas?", r"pediatri\w+",
            r"aspirantes?", r"bachiller\w*",
        ),
        domains=("educacion",),
        question="¿El sistema va a guardar datos de menores de edad?",
        open_question=(
            "¿Hay datos de menores de edad (estudiantes de primer semestre, "
            "aspirantes, pacientes)? Requieren autorización de padres o "
            "acudientes y un acceso más restringido."
        ),
    ),
    DomainConcern(
        key="retencion",
        label="Retención de los datos",
        covered=(
            r"retenci\w+", r"conserva\w*\s+(?:los\s+)?(?:datos|registros|eventos)",
            r"(?:borrar|eliminar|anonimizar|purgar)\s+(?:los\s+)?(?:datos|registros|eventos)",
            r"cuanto\s+tiempo\s+se\s+guarda\w*", r"\d+\s+(?:dias|meses|anos)\s+de\s+historia",
        ),
        triggers=(
            r"eventos?", r"registros?\s+de\s+(?:acceso|entrada|ingreso)", r"logs?",
            r"lectores?", r"sensores?", r"carne", r"historial", r"historicos?",
            r"auditoria", r"trazabilidad",
        ),
        domains=("salud", "educacion", "finanzas", "banca"),
        question="¿Cuánto tiempo deben conservarse los datos antes de borrarlos o anonimizarlos?",
        open_question=(
            "¿Cuánto tiempo se conservan los datos (eventos, historiales, "
            "registros de acceso) y cuándo se borran o anonimizan? Define la "
            "política antes de diseñar el almacenamiento."
        ),
    ),
    DomainConcern(
        key="respaldos",
        label="Respaldos de los datos",
        covered=(
            r"backups?", r"respaldos?", r"copias?\s+de\s+seguridad", r"recuperaci\w+\s+ante",
            r"restaur\w+",
        ),
        always=True,
        question="¿Cada cuánto deben respaldarse los datos del sistema?",
        open_question=(
            "¿Cada cuánto se respaldan los datos y cuánto se puede perder si falla "
            "el servidor? Muchos servicios gestionados lo incluyen; confírmalo."
        ),
    ),
)


def _regex(patterns: Iterable[str]) -> "re.Pattern[str]":
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(patterns) + r")(?![a-z])")


_COVERED = {concern.key: _regex(concern.covered) for concern in DOMAIN_CONCERNS}
_TRIGGERS = {
    concern.key: _regex(concern.triggers) for concern in DOMAIN_CONCERNS if concern.triggers
}


def _is_relevant(concern: DomainConcern, text: str, domain: str) -> bool:
    if concern.always:
        return True
    # El dominio puede venir del perfil (``domain``) o estar en el propio
    # texto ("una clínica de salud").
    if any(marker in domain or re.search(rf"\b{re.escape(marker)}", text) for marker in concern.domains):
        return True
    trigger = _TRIGGERS.get(concern.key)
    if trigger is not None and trigger.search(text):
        return True
    return bool(_COVERED[concern.key].search(text))


def relevant_concerns(project_text: str, domain: Optional[str] = None) -> list[DomainConcern]:
    """Preocupaciones que aplican a este proyecto, en el orden de la lista."""
    text = normalize_text(project_text)
    normalized_domain = normalize_text(domain)
    return [c for c in DOMAIN_CONCERNS if _is_relevant(c, text, normalized_domain)]


def uncovered_concerns(
    project_text: str,
    user_text: str,
    domain: Optional[str] = None,
    *,
    include_always: bool = True,
) -> list[DomainConcern]:
    """Relevantes que el usuario todavía no mencionó.

    ``project_text`` decide qué es relevante (descripción, resumen, respuestas,
    documentos); ``user_text`` decide qué está cubierto (lo que dijo el
    usuario). ``include_always=False`` deja fuera las que aplican a todo
    sistema (respaldos): la elicitación no las pregunta, van directo al ADR.
    """
    covered_text = normalize_text(user_text)
    return [
        concern
        for concern in relevant_concerns(project_text, domain)
        if (include_always or not concern.always)
        and not _COVERED[concern.key].search(covered_text)
    ]


def concern_by_question(question: str) -> Optional[DomainConcern]:
    """La preocupación cuya pregunta de elicitación es ``question`` (si hay)."""
    target = normalize_text(question).strip()
    return next(
        (c for c in DOMAIN_CONCERNS if normalize_text(c.question).strip() == target),
        None,
    )


def concern_mentioned(concern: DomainConcern, text: str) -> bool:
    """True si ``text`` ya trata la preocupación (usa alguno de sus términos)."""
    return bool(_COVERED[concern.key].search(normalize_text(text)))
