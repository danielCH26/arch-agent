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
    "red",
    "servidor",
    "contenedor",
    "docker",
    "kubernetes",
    "usuario",
    "usuario final",
    "cliente web",
    "navegador",
    "administrador",
    "actor",
    "externo",
    "tercero",
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
    """¿Es un nodo de infraestructura, almacén o actor, y no un módulo?"""
    normalized = normalize(name)
    if not normalized:
        return True
    return any(
        term == normalized or f" {term} " in f" {normalized} "
        for term in _NOT_A_MODULE
    )


def classify_module(name: str) -> tuple[str, str]:
    """``(tipo, término que lo decidió)``; término vacío si fue el valor por omisión."""
    normalized = f" {normalize(name)} "
    best_kind = ""
    best_term = ""
    for kind, terms in MODULE_KIND_TERMS.items():
        for term in terms:
            if f" {term} " in normalized and len(term) > len(best_term):
                best_kind, best_term = kind, term
    if not best_kind:
        return DEFAULT_MODULE_KIND, ""
    return best_kind, best_term


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

    A diferencia de ``parse_proposal_components``, acá interesa el bullet
    entero y no solo su parte en negrita: el framework suele estar en la
    descripción (``- **Backend**: FastAPI con SQLAlchemy``) y es justo lo que
    decide la convención.
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
    return lineas


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
    """Los módulos del sistema, del diagrama aprobado y de la propuesta.

    El diagrama manda: es lo que el usuario aprobó. Los componentes de la
    propuesta solo agregan los que el diagrama no nombró.
    """
    modules: list[DetectedModule] = []
    vistos: set[str] = set()

    def _agregar(nombre: str, origen: str) -> None:
        clave = normalize(nombre)
        if not clave or clave in vistos or is_infrastructure(nombre):
            return
        vistos.add(clave)
        kind, term = classify_module(nombre)
        modules.append(
            DetectedModule(name=nombre.strip(), kind=kind, matched_term=term, origin=origen)
        )

    for nombre in parse_mermaid_module_names(mermaid):
        _agregar(nombre, "diagrama")
    for nombre in componentes or ():
        _agregar(str(nombre), "propuesta")
    return modules


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
    modules = detect_modules(mermaid=mermaid, componentes=componentes)

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
    hay_frontend = any(_layer_of(m) == "frontend" for m in modules)
    if hay_frontend and frontend is None:
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
                    pattern_name=eleccion.pattern_name,
                    role=eleccion.role,
                    module=module.name,
                )
            )
        if module.uncovered_reason:
            warnings.append(f"{module.name}: {module.uncovered_reason}")

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
                if line.depth > convention.nesting_limit
            }
        )
        if excedidas:
            warnings.append(
                f"{convention.name} recomienda no pasar de {convention.nesting_limit} "
                f"niveles de carpetas; estas rutas lo exceden: {', '.join(excedidas)}."
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
        "unmatched_layers": list(plan.unmatched_layers),
        "module_kinds": list(VALID_MODULE_KINDS),
    }
