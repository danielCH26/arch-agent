"""Árbol de carpetas del repositorio a partir de convenciones y patrones.

Es el equivalente de ``app/core/deployment_mapper.py`` para la HU de la
estructura del repositorio, y sigue el mismo principio que allá resultó bien:

**la composición es determinista y cada línea carga su fuente.**

El LLM no escribe el árbol. Si lo escribiera, inventaría carpetas: es
exactamente lo que el criterio de aceptación "nada que no esté soportado por
el RAG" prohíbe. Acá el árbol se arma así:

1. Se detectan los módulos del sistema a partir del diagrama de arquitectura
   aprobado (los nodos del Mermaid) y de los componentes de la propuesta.
2. A cada módulo se le asigna un TIPO (``crud``, ``integracion``...) por
   coincidencia de términos, guardando el término que disparó la decisión.
3. Se elige la convención del stack por capa (backend y frontend), guardando
   también el término que la activó.
4. Se piden al catálogo los patrones cuyo ``applies_to_modules`` incluye el
   tipo del módulo, y se ubican sus aportes en la ranura que la convención
   define.
5. Toda línea del árbol sale con ``source_title`` y ``source_url``.

Lo que el LLM sí puede hacer después es redactar la justificación en prosa a
partir de este plan, que ya trae los hechos y las citas.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from app.core.convention_catalog import (
    Convention,
    match_convention,
)
from app.core.pattern_catalog import (
    KNOWN_UNCOVERED_MODULE_KINDS,
    VALID_MODULE_KINDS,
    patterns_for_module_kind,
)

_NON_WORD = re.compile(r"[^a-z0-9]+")

# ---------------------------------------------------------------------------
# Tipos de módulo
# ---------------------------------------------------------------------------
#
# Términos que asignan un tipo a un módulo. Gana el término MÁS LARGO, igual
# que en el mapeo de servicios de nube: "pasarela de pagos" le gana a "pagos".
# El término que gana se guarda en ``matched_term`` y viaja hasta la interfaz,
# así la decisión es auditable y no hay que adivinar por qué un módulo quedó
# clasificado como quedó.
MODULE_KIND_TERMS: dict[str, tuple[str, ...]] = {
    "autenticacion": (
        "autenticacion",
        "auth",
        "login",
        "inicio de sesion",
        "sesiones",
        "usuarios y roles",
        "permisos",
        "identidad",
        "oauth",
        "jwt",
    ),
    "integracion": (
        "integracion",
        "cliente externo",
        "servicio externo",
        "api externa",
        "pasarela de pagos",
        "proveedor externo",
        "webhook",
        "sincronizacion",
        # Red de seguridad por tecnología: un diagrama puede nombrar el nodo
        # por el SDK del proveedor ("Stripe SDK") en vez de por su rol. Sin
        # esto caía al tipo por omisión y recibía repositorio y unidad de
        # trabajo, como si fuera una entidad del dominio.
        "stripe",
        "paypal",
        "payu",
        "wompi",
        "mercadopago",
        "twilio",
        "sdk",
    ),
    "mensajeria": (
        "cola",
        "mensajeria",
        "broker",
        "eventos",
        "publicador",
        "suscriptor",
        "kafka",
        "rabbitmq",
        "sqs",
    ),
    "procesamiento": (
        "procesamiento",
        "worker",
        "job",
        "batch",
        "etl",
        "tarea programada",
        "ingesta",
        "transformacion",
        "motor de reglas",
    ),
    "reporte": (
        "reporte",
        "reportes",
        "tablero",
        "dashboard",
        "indicadores",
        "estadisticas",
        "analitica",
    ),
    "archivos": (
        "archivos",
        "documentos",
        "almacenamiento de archivos",
        "adjuntos",
        "carga de archivos",
        "storage",
    ),
    "notificaciones": (
        "notificaciones",
        "correo",
        "email",
        "mensajes al usuario",
        "alertas",
        "sms",
        # Por tecnología, misma razón que en `integracion`.
        "sendgrid",
        "mailgun",
        "smtp",
        "ses",
        "firebase cloud messaging",
    ),
    "ui": (
        "interfaz",
        "frontend",
        "front end",
        "pantalla",
        "vista web",
        "aplicacion web",
        "aplicacion movil",
        "spa",
        # Por tecnología. Es el caso que más duele si falla: un módulo de
        # interfaz mal clasificado se va al árbol del BACKEND y aparece con
        # repositorio y unidad de trabajo.
        "react",
        "vue",
        "angular",
        "svelte",
        "next js",
        "nuxt",
        "flutter",
    ),
    "api": (
        "api",
        "gateway",
        "bff",
        "endpoint",
        "controlador",
        "capa de entrada",
        "rest",
    ),
    "dominio": (
        "dominio",
        "reglas de negocio",
        "logica de negocio",
        "nucleo",
        "core de negocio",
    ),
    "consulta": (
        "consulta",
        "busqueda",
        "catalogo",
        "listado",
        "filtros",
    ),
    "crud": (
        "crud",
        "gestion",
        "administracion",
        "registro",
        "mantenimiento",
        "inventario",
        "pedidos",
        "clientes",
        "productos",
        "entidad",
    ),
}

# Tipo por defecto cuando ningún término matchea. Es el caso más común en un
# sistema de negocio (un módulo de entidad con altas, bajas y consultas) y
# tiene cobertura de patrones, así que el módulo no queda sin propuesta. Se
# marca con ``matched_term=""`` para que la interfaz pueda decir que fue el
# valor por omisión y no una coincidencia.
DEFAULT_MODULE_KIND = "crud"

# Nodos del diagrama que NO son módulos del repositorio: infraestructura,
# almacenes y actores. Si entraran, el árbol tendría una carpeta "PostgreSQL".
_NOT_A_MODULE = (
    "postgres",
    "postgresql",
    "mysql",
    "sql server",
    "oracle",
    "mongodb",
    "redis",
    "base de datos",
    "bd",
    "almacenamiento",
    "s3",
    "minio",
    "bucket",
    "balanceador",
    "load balancer",
    "cdn",
    "dns",
    "firewall",
    "vpc",
    "servidor",
    "contenedor",
    "docker",
    "kubernetes",
    # Servidores web, buscadores y servicios de red/cómputo de nube que los
    # diagramas nombran por la tecnología. Sin ellos terminaban como módulos
    # `crud` con su propio árbol (y `Load Balancer (Nginx)` sí se descartaba
    # mientras que `Nginx` solo no).
    "nginx",
    "elasticsearch",
    "cloudfront",
    "lambda",
    "usuario final",
    "cliente web",
    "navegador",
    "externo",
    "tercero",
    # Etiquetas de red que son habituales en los diagramas. Van como FRASE,
    # no como la palabra suelta «red»: así «Red de contactos», que sí es un
    # módulo de negocio, sigue entrando al árbol.
    "red privada",
    "red interna",
    "red publica",
    "red externa",
    "red local",
)

# Palabras demasiado comunes para descartar un nodo por contenerlas: solo
# cuentan cuando son el nombre COMPLETO. Con la comparación por palabra suelta,
# "Perfil de usuario", "Administrador de contenidos" y "Red de contactos"
# quedaban fuera del árbol como si fueran infraestructura, y son módulos de
# negocio de los más comunes.
_NOT_A_MODULE_EXACTO = (
    "usuario",
    "usuarios",
    "administrador",
    "administradores",
    "red",
    "actor",
    "actores",
)


# Palabras que no distinguen un módulo de otro, así que no sirven para decidir
# si dos nombres hablan de lo mismo. Sin esta lista, "Servicio de pagos" y
# "Servicio de correo" se fusionarían por compartir "servicio".
_TOKENS_VACIOS = frozenset(
    {
        "a", "al", "con", "de", "del", "e", "el", "en", "la", "las", "los",
        "o", "para", "por", "un", "una", "y",
        "app", "aplicacion", "capa", "componente", "modulo", "sistema",
        "servicio", "servicios", "web", "core",
        # "api" aparece en medio mundo ("SendGrid API", "FastAPI (API REST)")
        # y fusionaba módulos que no tienen nada que ver.
        "api",
    }
)

# Orden de preferencia cuando un nombre matchea VARIOS tipos. La longitud del
# término solo desempata DENTRO de un mismo tipo: entre tipos distintos, largo
# no significa específico.
#
# El caso que lo obligó: "Panel de administración (React)" matcheaba
# `administracion` (14, de crud) y `react` (5, de ui). Ganaba el largo, el
# módulo quedaba como crud y el frontend terminaba con repositorio y unidad de
# trabajo en el árbol del backend.
#
# `ui` va primero porque decide la CAPA, que es el error más caro. `crud` va
# último porque es el cajón de sastre.
KIND_PRIORITY: tuple[str, ...] = (
    "ui",
    "notificaciones",
    "integracion",
    "mensajeria",
    "procesamiento",
    "autenticacion",
    "reporte",
    "archivos",
    "api",
    "dominio",
    "consulta",
    "crud",
)


def normalize(text: str) -> str:
    lowered = (text or "").lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", stripped).strip()


def snake_case(text: str) -> str:
    """``"Gestión de Pedidos"`` -> ``"gestion_de_pedidos"``."""
    return "_".join(normalize(text).split()) or "modulo"


def pascal_case(text: str) -> str:
    """``"gestión de pedidos"`` -> ``"GestionDePedidos"``."""
    return "".join(part.capitalize() for part in normalize(text).split()) or "Modulo"


def is_infrastructure(name: str) -> bool:
    """¿Es un nodo de infraestructura, almacén o actor, y no un módulo?

    Un nombre que SÍ matchea un tipo de módulo no es infraestructura, aunque
    contenga una palabra de la lista. Las dos listas se pisaban: «externo»,
    «tercero» y «almacenamiento» sacaban del árbol justo a los módulos cuyos
    términos de `integracion` y `archivos` son «servicio externo», «proveedor
    externo» y «almacenamiento de archivos» — esos términos no podían
    matchear nunca. Se clasifica primero y se descarta solo lo que no tiene
    tipo.
    """
    normalized = normalize(name)
    if not normalized:
        return True
    # Las palabras genéricas (`usuario`, `administrador`, `red`) solo cuentan
    # si son el nombre entero; las demás, también como palabra suelta.
    if normalized not in _NOT_A_MODULE_EXACTO and not any(
        term == normalized or f" {term} " in f" {normalized} "
        for term in _NOT_A_MODULE
    ):
        return False
    # Tiene palabra de infraestructura: solo se descarta si además no
    # matcheó ningún término de tipo de módulo.
    _kind, term = classify_module(name)
    return not term


# Vocabulario con el que se decide si un descarte es EVIDENTE: todo nombre
# cuyas palabras sean de infraestructura, relleno gramatical o números de
# versión no tiene nada que revisar. Con comparar solo el nombre exacto, los
# diagramas reales (que nombran por tecnología y versión: «PostgreSQL 16»,
# «Redis Cache», «Amazon S3», «Load Balancer (Nginx)») hacían saltar el aviso
# en casi todos los ADR.
#
# Las palabras de infraestructura salen de las mismas listas con las que se
# descarta (`_NOT_A_MODULE` y `_NOT_A_MODULE_EXACTO`), así que no hay que
# mantener dos listas. Los calificativos de abajo son los que acompañan a una
# tecnología sin decir nada del negocio.
_PALABRAS_DE_RELLENO = frozenset(
    {"a", "al", "con", "de", "del", "e", "el", "en", "la", "las", "los", "o",
     "para", "por", "un", "una", "y"}
)
_CALIFICATIVOS_DE_INFRA = frozenset(
    {
        "cache", "db", "cluster", "atlas", "amazon", "aws", "gcp", "azure",
        "google", "cloud", "nube", "compose", "swarm", "managed", "gestionado",
        "instance", "instancia", "replica", "nodo", "node", "pod", "host", "vm",
        "ec2", "rds", "ssl", "tls", "http", "https", "tcp", "ip", "subnet",
        "subred", "web",
    }
)
_VERSION = re.compile(r"v?\d+")
_PALABRAS_DE_INFRA = frozenset(
    palabra
    for termino in (*_NOT_A_MODULE, *_NOT_A_MODULE_EXACTO)
    for palabra in normalize(termino).split()
)


def discard_is_doubtful(name: str) -> bool:
    """¿Este descarte merece un aviso, o es infraestructura evidente?

    Avisar de todos los descartes convertía el aviso en ruido: un diagrama
    normal («Usuario → Frontend → API → PostgreSQL, Redis») hacía que TODOS
    los ADR pidieran revisar que PostgreSQL no fuera un módulo. Decir
    "revisá esto" cuando no hay nada que revisar le quita credibilidad a los
    avisos de verdad.

    El criterio: el descarte es discutible si el nombre tiene ALGUNA palabra
    que no sea de infraestructura, relleno gramatical ni número de versión.

    * Evidente (no avisa): «PostgreSQL», «PostgreSQL 16», «Redis Cache»,
      «MongoDB Atlas», «Base de datos (PostgreSQL)», «Amazon S3»,
      «Docker Compose», «Load Balancer (Nginx)», «Red privada (VPC)».
    * Discutible (avisa): «Servidor de aplicaciones» o «Servidor de pagos»:
      se descartan por «servidor», pero «aplicaciones» o «pagos» podrían ser
      un módulo mal nombrado, y eso es lo que hay que revisar. (Un nombre que
      sí matchea un tipo de módulo, como «Almacenamiento de reportes», no se
      descarta, así que nunca llega aquí.)
    """
    normalized = normalize(name)
    if not normalized:
        return False
    for palabra in normalized.split():
        if (
            palabra in _PALABRAS_DE_INFRA
            or palabra in _CALIFICATIVOS_DE_INFRA
            or palabra in _PALABRAS_DE_RELLENO
            or _VERSION.fullmatch(palabra)
        ):
            continue
        return True
    return False


def classify_module(name: str) -> tuple[str, str]:
    """``(tipo, término que lo decidió)``; término vacío si fue el valor por omisión.

    Entre tipos distintos manda ``KIND_PRIORITY``; la longitud del término
    solo desempata dentro del mismo tipo.
    """
    normalized = f" {normalize(name)} "
    prioridad = {kind: i for i, kind in enumerate(KIND_PRIORITY)}
    mejor: tuple[int, int, str, str] | None = None
    for kind, terms in MODULE_KIND_TERMS.items():
        orden = prioridad.get(kind, len(KIND_PRIORITY))
        for term in terms:
            if f" {term} " not in normalized:
                continue
            # Menor índice de prioridad gana; a igual tipo, término más largo.
            candidato = (-orden, len(term), kind, term)
            if mejor is None or candidato > mejor:
                mejor = candidato
    if mejor is None:
        return DEFAULT_MODULE_KIND, ""
    return mejor[2], mejor[3]


# ---------------------------------------------------------------------------
# Estructuras del plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StructureLine:
    """Una línea del árbol con su justificación y su fuente."""

    path: str
    note: str
    source_title: str
    source_url: str
    origin: str  # "convencion" | "patron"
    # De qué convención salió la línea. Sin esto, el aviso de anidamiento de
    # React se aplicaba a las rutas de Spring Boot: el bucle comparaba TODAS
    # las líneas contra el límite de CADA convención.
    convention_id: str = ""
    pattern_name: str = ""
    role: str = ""
    module: str = ""

    @property
    def depth(self) -> int:
        return len([part for part in self.path.strip("/").split("/") if part])


@dataclass(frozen=True)
class PatternChoice:
    """Patrón elegido para un módulo, con por qué se eligió."""

    pattern_name: str
    role: str
    justification: str
    matched_kind: str
    source_title: str
    source_url: str
    placed_path: str
    placed: bool


@dataclass(frozen=True)
class DetectedModule:
    name: str
    kind: str
    matched_term: str
    origin: str  # "diagrama" | "propuesta"
    patterns: tuple[PatternChoice, ...] = field(default=())
    uncovered_reason: str = ""


@dataclass(frozen=True)
class StructurePlan:
    modules: tuple[DetectedModule, ...]
    backend: Convention | None
    backend_term: str
    frontend: Convention | None
    frontend_term: str
    lines: tuple[StructureLine, ...]
    warnings: tuple[str, ...]
    # Aclaraciones que NO son pendientes. Van aparte de `warnings` justamente
    # por eso: decirle al usuario "revisá esto" cuando no hay nada que revisar
    # le hace perder tiempo y le quita credibilidad a los avisos de verdad.
    notes: tuple[str, ...]
    unmatched_layers: tuple[str, ...]

    def tree_text(self) -> str:
        """El árbol como texto plano, que es lo que pide la historia."""
        return render_tree(self.lines)


# ---------------------------------------------------------------------------
# Detección de módulos
# ---------------------------------------------------------------------------


def parse_mermaid_module_names(mermaid: str) -> list[str]:
    """Etiquetas de los nodos del diagrama, en orden y sin repetir.

    Se reusa deliberadamente el analizador del diagrama de despliegue, que ya
    maneja las formas de nodo, las etiquetas de arista y las listas con ``&``.
    Reimplementarlo acá habría duplicado los mismos errores que allá costó
    encontrar.
    """
    from app.core.deployment_mapper import parse_mermaid_nodes

    nombres: list[str] = []
    vistos: set[str] = set()
    # ``parse_mermaid_nodes`` devuelve ``{id_del_nodo: etiqueta}``.
    for etiqueta in parse_mermaid_nodes(mermaid or "").values():
        etiqueta = (etiqueta or "").strip()
        if not etiqueta:
            continue
        clave = normalize(etiqueta)
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        nombres.append(etiqueta)
    return nombres


_TECH_HEADING_RE = re.compile(
    r"^\s{0,3}#{1,6}\s*\d*\.?\s*tecnolog", re.IGNORECASE
)


def parse_proposal_technologies(markdown: str) -> list[str]:
    """Las líneas de la sección "Tecnologías" de la propuesta, completas.

    Lee DOS formatos, porque el generador de propuestas usa los dos:

    - viñetas (``- **Backend**: FastAPI con SQLAlchemy``), y
    - tabla markdown (``| FastAPI (Python) | Framework ASGI… | … |``), que es
      lo que produce hoy.

    Solo leer viñetas hacía que una propuesta con tabla cayera al respaldo de
    buscar en todo el documento, y la convención se elegía por un término
    suelto de cualquier párrafo en vez de por el stack declarado.

    A diferencia de ``parse_proposal_components``, acá interesa la línea
    entera y no solo su parte en negrita: el framework suele estar en la
    descripción y es justo lo que decide la convención.
    """
    from app.core.deployment_mapper import _ANY_HEADING_RE, _BULLET_RE

    lineas: list[str] = []
    dentro = False
    for line in (markdown or "").splitlines():
        if _TECH_HEADING_RE.match(line):
            dentro = True
            continue
        if dentro and _ANY_HEADING_RE.match(line):
            break
        if not dentro:
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            texto = bullet.group("body").replace("*", " ").strip()
            if texto:
                lineas.append(texto)
            continue

        # Fila de tabla. Se descarta el separador (``| --- | --- |``) y la
        # fila de encabezados, que no nombran ninguna tecnología.
        despojada = line.strip()
        if despojada.startswith("|") and despojada.endswith("|"):
            celdas = [c.strip() for c in despojada.strip("|").split("|")]
            if not celdas or all(set(c) <= set("-: ") for c in celdas):
                continue
            texto = " ".join(c.replace("*", " ") for c in celdas if c).strip()
            if texto and normalize(texto) not in _ENCABEZADOS_DE_TABLA:
                lineas.append(texto)
    return lineas


# Encabezados de la tabla de tecnologías, normalizados: su fila no aporta
# ningún término de stack y matchearla sería ruido.
_ENCABEZADOS_DE_TABLA = frozenset(
    {
        "tecnologia justificacion requisito que lo motiva",
        "tecnologia justificacion requisito",
    }
)


_PRIMARY_PATTERN_RE = re.compile(
    r"patr[oó]n\s+principal\s*:\s*(?P<nombre>[^\n]+)", re.IGNORECASE
)


def parse_primary_pattern(markdown: str) -> str:
    """El patrón principal que declara la propuesta, o cadena vacía.

    Los asteriscos se quitan ANTES de buscar: la propuesta escribe el rótulo
    en negrita (``**Patrón principal:** Serverless``), y con el ``**`` pegado
    a los dos puntos la captura arrancaba en un asterisco y no matcheaba nada.
    """
    limpio = (markdown or "").replace("*", "")
    match = _PRIMARY_PATTERN_RE.search(limpio)
    if not match:
        return ""
    # Puede traer guiones tipográficos ("Function‑as‑a‑Service") y puntuación
    # final; los primeros se conservan porque `pattern_family` los normaliza.
    nombre = match.group("nombre").strip().rstrip(".;,")
    return " ".join(nombre.split())


# Familias de patrón cuyo repositorio NO se parece a una aplicación única. Las
# cuatro convenciones de hoy describen un solo desplegable (un paquete Python,
# un proyecto Django, un proyecto Spring), así que para estas el árbol es una
# aproximación y hay que decirlo: un repo serverless se organiza por función
# más la plantilla de infraestructura, y uno de microservicios por servicio.
_FAMILIAS_SIN_CONVENCION = frozenset({"serverless", "distribuido"})


def stack_terms(markdown: str) -> tuple[list[str], bool]:
    """``(términos para elegir la convención, si vinieron de la sección)``.

    Se prefiere la sección "Tecnologías" porque es donde la propuesta declara
    el stack. Solo si no hay sección se cae a todo el documento, y se avisa:
    buscar en todo el markdown puede matchear un framework que la propuesta
    apenas menciona al comparar alternativas.
    """
    seccion = parse_proposal_technologies(markdown)
    if seccion:
        return seccion, True
    return [markdown or ""], False


def detect_modules(
    *,
    mermaid: str = "",
    componentes: Sequence[str] = (),
) -> list[DetectedModule]:
    """Los módulos detectados. Para los nodos descartados, ver
    ``detect_modules_con_descartes``."""
    return detect_modules_con_descartes(mermaid=mermaid, componentes=componentes)[0]


def detect_modules_con_descartes(
    *,
    mermaid: str = "",
    componentes: Sequence[str] = (),
) -> tuple[list[DetectedModule], list[str]]:
    """Los módulos del sistema, del diagrama aprobado y de la propuesta.

    El diagrama manda: es lo que el usuario aprobó. Los componentes de la
    propuesta solo agregan los que el diagrama no nombró.
    """
    del_diagrama = parse_mermaid_module_names(mermaid)
    de_la_propuesta = [str(c).strip() for c in (componentes or ()) if str(c).strip()]

    # Los nodos del diagrama suelen venir abreviados y nombrados por
    # TECNOLOGÍA ("React + TypeScript", "Stripe SDK"), mientras que los
    # componentes de la propuesta los nombran por ROL ("Frontend Web (React +
    # TypeScript)", "Integración de pagos (Stripe SDK)"). El rol es lo que
    # permite clasificar bien el módulo, así que cuando los dos hablan de lo
    # mismo se conserva el NOMBRE MÁS DESCRIPTIVO.
    #
    # Sin esto, "React + TypeScript" no matcheaba ningún término de interfaz,
    # caía al tipo por omisión (crud) y terminaba con un repositorio y una
    # unidad de trabajo de backend: el frontend en `app/repositories/`.
    # Comparar por subcadena no alcanza: "FastAPI (API REST)" del diagrama y
    # "API REST (FastAPI)" de la propuesta son el mismo módulo y ninguno
    # contiene al otro, así que salían DUPLICADOS, cada uno con sus carpetas.
    # Se comparan los tokens significativos: si comparten alguno, hablan de lo
    # mismo. Es deliberadamente conservador — ante la duda se fusiona, porque
    # un duplicado visible es peor que un módulo de menos.
    def _tokens(texto: str) -> set[str]:
        return {t for t in normalize(texto).split() if t not in _TOKENS_VACIOS}

    def _mismo_modulo(a: str, b: str) -> bool:
        ta, tb = _tokens(a), _tokens(b)
        if not ta or not tb:
            return False
        return bool(ta & tb)

    modules: list[DetectedModule] = []
    vistos: set[str] = set()
    # Nodos que se descartaron por parecer infraestructura. Se devuelven para
    # que `build_plan` los avise: descartar en silencio es justo lo que hacía
    # desaparecer módulos de negocio sin que nadie se enterara.
    descartados: list[str] = []

    def _agregar(nombre: str, origen: str) -> None:
        clave = normalize(nombre)
        if not clave or clave in vistos:
            return
        if is_infrastructure(nombre):
            if clave not in {normalize(d) for d in descartados}:
                descartados.append(nombre.strip())
            return
        vistos.add(clave)
        kind, term = classify_module(nombre)
        modules.append(
            DetectedModule(name=nombre.strip(), kind=kind, matched_term=term, origin=origen)
        )

    # Cuántos nodos del diagrama reclama cada componente. Un componente que
    # reclaman DOS o más es demasiado genérico para renombrar con él: si se
    # usara, los dos nodos pasarían a llamarse igual y el deduplicado se
    # comería uno sin avisar.
    #
    # El caso: diagrama con "Pedidos API" y "Pedidos Worker", componente
    # "Gestión de pedidos". Los dos comparten el token `pedidos`, los dos se
    # renombraban igual y el Worker (que es `procesamiento`) desaparecía.
    reclamos: dict[str, int] = {}
    for etiqueta in del_diagrama:
        for componente in de_la_propuesta:
            if _mismo_modulo(etiqueta, componente):
                reclamos[normalize(componente)] = reclamos.get(normalize(componente), 0) + 1

    # Un componente se considera representado SOLO en dos casos:
    #
    #   a) se usó para renombrar un nodo, o
    #   b) lo reclaman dos o más nodos, y entonces esos nodos ya lo cubren
    #      entre todos (es el caso de "Pedidos API" + "Pedidos Worker").
    #
    # El resto se agrega como módulo propio. Antes se marcaba representado
    # TODO lo que un nodo reclamara, y eso perdía módulos por el otro lado:
    # un nodo que reclama dos componentes renombraba con uno y descartaba el
    # otro sin avisar. Con `[Backend FastAPI]` y los componentes "Servicio de
    # pedidos (FastAPI)" y "Servicio de pagos (FastAPI)", pagos desaparecía.
    #
    # Cada componente se usa para renombrar como máximo una vez: dos nodos no
    # pueden quedar con el mismo nombre.
    representados: set[str] = {
        clave for clave, veces in reclamos.items() if veces >= 2
    }
    # Cada nodo CONSUME un solo componente: el más descriptivo de los que
    # matchea. Lo consume aunque no lo use para renombrar —cuando su propia
    # etiqueta ya es igual de buena— porque igual habla de lo mismo y
    # agregarlo aparte daría el módulo dos veces: es lo que pasaba con
    # `FastAPI (API REST)` del diagrama y `API REST (FastAPI)` de la
    # propuesta, que normalizan al mismo largo.
    #
    # Los componentes que ningún nodo consume sí entran como módulos propios.
    consumidos: set[str] = set()
    for etiqueta in del_diagrama:
        candidatos = [
            c
            for c in de_la_propuesta
            if _mismo_modulo(etiqueta, c)
            and reclamos.get(normalize(c), 0) == 1
            and normalize(c) not in consumidos
        ]
        mejor = max(candidatos, key=len, default="")
        if mejor:
            consumidos.add(normalize(mejor))
        if mejor and len(normalize(mejor)) > len(normalize(etiqueta)):
            _agregar(mejor, "diagrama")
        else:
            _agregar(etiqueta, "diagrama")

    for nombre in de_la_propuesta:
        clave = normalize(nombre)
        if clave in representados or clave in consumidos:
            continue
        _agregar(nombre, "propuesta")
    return modules, descartados


# ---------------------------------------------------------------------------
# Elección de patrones por módulo
# ---------------------------------------------------------------------------


def choose_patterns(module: DetectedModule, convention: Convention | None) -> DetectedModule:
    """Los patrones aplicables al tipo del módulo, ubicados en la convención.

    Un patrón aplicable cuyo rol la convención no sabe ubicar se devuelve con
    ``placed=False``: se informa que aplica y por qué, y que la convención del
    stack no documenta una carpeta para él. Eso es más honesto (y más útil)
    que ubicarlo en una ruta inventada.
    """
    aplicables = patterns_for_module_kind(module.kind)
    if not aplicables:
        razon = (
            f"No hay en la base ningún patrón declarado aplicable a un módulo de "
            f"tipo '{module.kind}'."
            if module.kind in KNOWN_UNCOVERED_MODULE_KINDS
            else f"Ningún patrón de la base declara aplicar a un módulo de tipo '{module.kind}'."
        )
        return DetectedModule(
            name=module.name,
            kind=module.kind,
            matched_term=module.matched_term,
            origin=module.origin,
            patterns=(),
            uncovered_reason=razon,
        )

    elegidos: list[PatternChoice] = []
    for entry in sorted(aplicables, key=lambda e: e["pattern_name"]):
        for aporte in entry["contributions"]:
            ruta, ubicado = _place(module, convention, aporte)
            elegidos.append(
                PatternChoice(
                    pattern_name=entry["pattern_name"],
                    role=aporte["role"],
                    justification=aporte["note"],
                    matched_kind=module.kind,
                    source_title=aporte["source_title"],
                    source_url=aporte["source_url"],
                    placed_path=ruta,
                    placed=ubicado,
                )
            )
    return DetectedModule(
        name=module.name,
        kind=module.kind,
        matched_term=module.matched_term,
        origin=module.origin,
        patterns=tuple(elegidos),
        uncovered_reason="",
    )


def _place(
    module: DetectedModule, convention: Convention | None, aporte: dict
) -> tuple[str, bool]:
    """La ruta donde va el aporte del patrón, y si se pudo ubicar."""
    if convention is None:
        return "", False
    if aporte["role"] in convention.documented_roles:
        # La convención ya documenta ese rol en su propio `module_tree`: no hay
        # que agregar una línea, el patrón solo justifica la que ya existe.
        nodo = next(
            (n for n in convention.module_tree if n.role == aporte["role"]), None
        )
        if nodo is not None:
            return (
                nodo.rendered(
                    module=snake_case(module.name), Module=pascal_case(module.name)
                ),
                True,
            )
    slot = convention.pattern_slot
    if not slot:
        return "", False
    # La plantilla DEBE traer un marcador de rol. Sin él no puede distinguir
    # un repositorio de un servicio y todos los aportes caerían en la misma
    # ruta, que además se vería como una sola línea tras el deduplicado.
    if not any(marca in slot for marca in ("{role_dir}", "{role_file}", "{Role}")):
        return "", False
    ruta = (
        slot.replace("{module}", snake_case(module.name))
        .replace("{Module}", pascal_case(module.name))
        .replace("{role_dir}", aporte["dir_name"])
        .replace("{role_file}", aporte["file_name"])
        .replace("{Role}", pascal_case(module.name) + aporte["class_name"])
    )
    # Si la plantilla no consumió ningún marcador de rol, la convención no sabe
    # ubicar aportes de patrones y no se inventa una ruta.
    if "{" in ruta:
        return "", False
    return ruta, True


# ---------------------------------------------------------------------------
# Composición del árbol
# ---------------------------------------------------------------------------


def _layer_of(module: DetectedModule) -> str:
    return "frontend" if module.kind == "ui" else "backend"


def build_plan(
    *,
    mermaid: str = "",
    componentes: Sequence[str] = (),
    tecnologias: Sequence[str] = (),
    proposal_markdown: str = "",
) -> StructurePlan:
    """El plan completo: módulos, convenciones, árbol y advertencias."""
    # Los componentes de la propuesta nombran los módulos por ROL, mientras que
    # el diagrama los abrevia por tecnología. `detect_modules` cruza las dos
    # listas y se queda con el nombre más descriptivo, así que conviene pasarle
    # siempre los de la propuesta aunque el llamador no los dé.
    if not componentes and proposal_markdown:
        from app.core.deployment_mapper import parse_proposal_components

        componentes = parse_proposal_components(proposal_markdown)

    modules, descartados = detect_modules_con_descartes(
        mermaid=mermaid, componentes=componentes
    )

    warnings: list[str] = []

    # Para elegir la convención se mira lo que describe el stack: las
    # tecnologías que pasen por parámetro, la sección "Tecnologías" de la
    # propuesta, y los nombres de los componentes, donde a veces aparece el
    # framework ("API FastAPI").
    terminos = list(tecnologias or ())
    if proposal_markdown:
        del_documento, de_la_seccion = stack_terms(proposal_markdown)
        terminos += del_documento
        if not de_la_seccion:
            warnings.append(
                "La propuesta no tiene una sección de tecnologías, así que el stack "
                "se dedujo de todo el documento; conviene revisar que la convención "
                "elegida sea la correcta."
            )
    terminos += [m.name for m in modules]
    backend, backend_term = match_convention(terminos, layer="backend")
    frontend, frontend_term = match_convention(terminos, layer="frontend")

    unmatched: list[str] = []
    if backend is None:
        unmatched.append("backend")
        warnings.append(
            "No se reconoció el stack de backend en las tecnologías de la propuesta, "
            "así que no hay convención oficial que respalde un árbol para esa capa."
        )
    # La convención se elige por TECNOLOGÍA, y eso solo no alcanza: un
    # proyecto serverless escrito con FastAPI matchea la convención de FastAPI
    # y recibiría el árbol de una aplicación monolítica (`app/main.py`,
    # `app/routers/`), que no es como se organiza un repo serverless. Como no
    # hay convención con fuente para esos estilos, se avisa en vez de dar una
    # guía que la fuente no respalda.
    principal = parse_primary_pattern(proposal_markdown)
    if principal and backend is not None:
        from app.core.pattern_catalog import pattern_family

        info = pattern_family(principal)
        if info and info["family"] in _FAMILIAS_SIN_CONVENCION:
            warnings.append(
                f"La arquitectura aprobada es «{principal}», pero la convención "
                f"reconocida ({backend.name}) describe una aplicación única. El "
                "árbol sirve para organizar el código de cada pieza, no para el "
                "repositorio completo: revisá cómo se reparte entre funciones o "
                "servicios."
            )

    notes: list[str] = []

    # La documentación de React escribe los archivos con extensión `.js`, y el
    # árbol los copia tal cual: inventar `.tsx` sería atribuirle a la fuente
    # algo que no dice. Pero en un proyecto TypeScript eso despista, así que
    # se aclara en vez de callarlo.
    if frontend is not None and any("typescript" in normalize(t) for t in terminos):
        notes.append(
            f"{frontend.name} escribe los archivos con extensión «.js» y el árbol "
            "los copia de ahí. Como el proyecto usa TypeScript, en la práctica son "
            "«.tsx» para los componentes y «.ts» para el resto."
        )

    hay_frontend = any(_layer_of(m) == "frontend" for m in modules)
    if hay_frontend and frontend is None:
        if backend is not None and backend.serves_frontend:
            # No hay hueco: el framework del backend sirve la interfaz y sus
            # módulos ya traen plantillas y estáticos. Es una aclaración, no
            # un pendiente.
            notes.append(
                f"La interfaz la sirve {backend.name} con sus propias plantillas, "
                "así que no hay un árbol de frontend aparte: las plantillas y los "
                "archivos estáticos de cada módulo ya están en el árbol."
            )
        else:
            unmatched.append("frontend")
            warnings.append(
                "Hay módulos de interfaz pero no se reconoció el stack de frontend, "
                "así que esos módulos quedan sin árbol."
            )

    resueltos = tuple(
        choose_patterns(m, frontend if _layer_of(m) == "frontend" else backend)
        for m in modules
    )

    lines: list[StructureLine] = []
    for convention in (backend, frontend):
        if convention is None:
            continue
        if convention is frontend and not hay_frontend:
            continue
        for nodo in convention.base_tree:
            lines.append(
                StructureLine(
                    path=nodo.path,
                    note=nodo.note,
                    source_title=nodo.source_title,
                    source_url=nodo.source_url,
                    origin="convencion",
                    convention_id=convention.convention_id,
                    role=nodo.role or "",
                )
            )

    for module in resueltos:
        convention = frontend if _layer_of(module) == "frontend" else backend
        if convention is None:
            continue
        valores = {"module": snake_case(module.name), "Module": pascal_case(module.name)}
        for nodo in convention.module_tree:
            lines.append(
                StructureLine(
                    path=nodo.rendered(**valores),
                    note=nodo.note,
                    source_title=nodo.source_title,
                    source_url=nodo.source_url,
                    origin="convencion",
                    convention_id=convention.convention_id,
                    role=nodo.role or "",
                    module=module.name,
                )
            )
        for eleccion in module.patterns:
            if not eleccion.placed:
                warnings.append(
                    f"{module.name}: {eleccion.pattern_name} aplica a este módulo, pero "
                    f"{convention.name} no documenta dónde ubicarlo; queda sin carpeta en el árbol."
                )
                continue
            if any(line.path == eleccion.placed_path for line in lines):
                # Ya la puso la convención (rol documentado): el patrón no
                # agrega una línea, solo la justifica.
                continue
            lines.append(
                StructureLine(
                    path=eleccion.placed_path,
                    note=eleccion.justification,
                    source_title=eleccion.source_title,
                    source_url=eleccion.source_url,
                    origin="patron",
                    convention_id=convention.convention_id,
                    pattern_name=eleccion.pattern_name,
                    role=eleccion.role,
                    module=module.name,
                )
            )
        if module.uncovered_reason:
            warnings.append(f"{module.name}: {module.uncovered_reason}")

    # Dos módulos pueden caer en la misma ruta y el deduplicado de abajo los
    # junta en una línea, haciendo desaparecer uno.
    #
    # Antes había acá un razonamiento de que no podía pasar: `snake_case` es
    # inyectiva sobre `normalize`, y `_agregar` deduplica por ese valor. Era
    # cierto para `snake_case` y FALSO para el árbol completo: `pascal_case`
    # NO es inyectiva ("Pedidos 2" y "Pedidos2" dan los dos `Pedidos2`), y las
    # convenciones de Spring Boot y React arman las rutas con él.
    #
    # Por eso el aviso se calcula sobre las RUTAS ya generadas y no sobre los
    # nombres: así cubre cualquier función de nombrado, presente o futura.
    por_ruta: dict[str, set[str]] = {}
    for line in lines:
        if line.module:
            por_ruta.setdefault(line.path, set()).add(line.module)
    for ruta, duenos in sorted(por_ruta.items()):
        if len(duenos) > 1:
            warnings.append(
                f"Estos módulos caen en la misma ruta «{ruta}» y se muestran como "
                f"una sola línea: {', '.join(sorted(duenos))}. Renombrá alguno en "
                "el diagrama para separarlos."
            )


    # Deduplicado conservando el orden y el límite de anidamiento.
    unicas: list[StructureLine] = []
    vistas: set[str] = set()
    for line in lines:
        if line.path in vistas:
            continue
        vistas.add(line.path)
        unicas.append(line)

    for convention in (backend, frontend):
        if convention is None or not convention.nesting_limit:
            continue
        excedidas = sorted(
            {
                line.path
                for line in unicas
                if line.convention_id == convention.convention_id
                and line.depth > convention.nesting_limit
            }
        )
        if excedidas:
            warnings.append(
                f"{convention.name} recomienda no pasar de {convention.nesting_limit} "
                f"niveles de carpetas; estas rutas lo exceden: {', '.join(excedidas)}."
            )

    # Solo se avisa de los descartes DISCUTIBLES (ver `discard_is_doubtful`).
    # Los evidentes —actores y tecnologías de infraestructura— se mencionan
    # como aclaración, sin pedirle nada al usuario.
    dudosos = [d for d in descartados if discard_is_doubtful(d)]
    evidentes = [d for d in descartados if d not in dudosos]
    if dudosos:
        warnings.append(
            "Estos nodos del diagrama se trataron como infraestructura y quedaron "
            f"fuera del árbol: {', '.join(dudosos)}. Si alguno es un módulo del "
            "sistema, renombralo en el diagrama para que no se confunda."
        )
    if evidentes:
        notes.append(
            "Estos nodos del diagrama son infraestructura o actores, así que no "
            f"llevan carpetas propias: {', '.join(evidentes)}."
        )

    if not modules:
        warnings.append(
            "No se detectó ningún módulo en el diagrama aprobado ni en los componentes "
            "de la propuesta, así que no hay nada que estructurar."
        )

    return StructurePlan(
        modules=resueltos,
        backend=backend,
        backend_term=backend_term,
        frontend=frontend,
        frontend_term=frontend_term,
        lines=tuple(sorted(unicas, key=lambda line: line.path)),
        warnings=tuple(dict.fromkeys(warnings)),
        notes=tuple(dict.fromkeys(notes)),
        unmatched_layers=tuple(unmatched),
    )


def render_tree(lines: Iterable[StructureLine]) -> str:
    """El árbol como texto con guías, ordenado por ruta.

    Texto plano a propósito: el entregable de la historia es un árbol legible
    en el ADR y en la interfaz, y un árbol de carpetas no necesita el render
    por navegador que sí necesitaba el diagrama de despliegue.
    """
    rutas = sorted({line.path for line in lines})
    if not rutas:
        return ""

    # Se arma un árbol anidado de verdad. Indentar por profundidad sin emitir
    # las carpetas intermedias deja líneas huérfanas: `app/ports/x.py` se vería
    # sangrado sin que `ports/` aparezca nunca.
    raiz: dict[str, dict] = {}
    for ruta in rutas:
        partes = [p for p in ruta.strip("/").split("/") if p]
        if not partes:
            continue
        es_carpeta = ruta.rstrip().endswith("/")
        nodo = raiz
        for indice, parte in enumerate(partes):
            ultimo = indice == len(partes) - 1
            # Una parte intermedia es siempre carpeta; la última lo es solo si
            # la ruta terminaba en "/".
            hijos = nodo.setdefault(parte, {"dir": not ultimo or es_carpeta, "hijos": {}})
            if not ultimo:
                hijos["dir"] = True
            nodo = hijos["hijos"]

    salida: list[str] = []

    def _emitir(nodo: dict[str, dict], nivel: int) -> None:
        # Carpetas primero y luego archivos, cada grupo alfabético: es como se
        # lee un árbol de repositorio en cualquier herramienta.
        for nombre, datos in sorted(
            nodo.items(), key=lambda item: (not item[1]["dir"], item[0].lower())
        ):
            sufijo = "/" if datos["dir"] else ""
            salida.append(f"{'    ' * nivel}{nombre}{sufijo}")
            if datos["hijos"]:
                _emitir(datos["hijos"], nivel + 1)

    _emitir(raiz, 0)
    return "\n".join(salida)


def plan_to_dict(plan: StructurePlan) -> dict:
    """El plan serializable, que es lo que viaja a la interfaz y al adjunto."""
    return {
        "backend": (
            {
                "convention_id": plan.backend.convention_id,
                "name": plan.backend.name,
                "summary": plan.backend.summary,
                "matched_term": plan.backend_term,
                "nesting_limit": plan.backend.nesting_limit,
                "fuentes": [dict(f) for f in plan.backend.fuentes],
            }
            if plan.backend
            else None
        ),
        "frontend": (
            {
                "convention_id": plan.frontend.convention_id,
                "name": plan.frontend.name,
                "summary": plan.frontend.summary,
                "matched_term": plan.frontend_term,
                "nesting_limit": plan.frontend.nesting_limit,
                "fuentes": [dict(f) for f in plan.frontend.fuentes],
            }
            if plan.frontend
            else None
        ),
        "modules": [
            {
                "name": m.name,
                "kind": m.kind,
                "matched_term": m.matched_term,
                "origin": m.origin,
                "uncovered_reason": m.uncovered_reason,
                "patterns": [
                    {
                        "pattern_name": p.pattern_name,
                        "role": p.role,
                        "justification": p.justification,
                        "matched_kind": p.matched_kind,
                        "source_title": p.source_title,
                        "source_url": p.source_url,
                        "path": p.placed_path,
                        "placed": p.placed,
                    }
                    for p in m.patterns
                ],
            }
            for m in plan.modules
        ],
        "lines": [
            {
                "path": line.path,
                "note": line.note,
                "origin": line.origin,
                "convention_id": line.convention_id,
                "pattern_name": line.pattern_name,
                "role": line.role,
                "module": line.module,
                "source_title": line.source_title,
                "source_url": line.source_url,
            }
            for line in plan.lines
        ],
        "tree_text": plan.tree_text(),
        "warnings": list(plan.warnings),
        "notes": list(plan.notes),
        "unmatched_layers": list(plan.unmatched_layers),
        "module_kinds": list(VALID_MODULE_KINDS),
    }
