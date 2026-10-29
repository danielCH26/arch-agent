"""
Mapeo "componente de la arquitectura aprobada -> servicio de la nube".

Entrada: el Mermaid del diagrama aprobado (HU6) y el markdown de la
propuesta aprobada. Salida: un plan de despliegue con un servicio por
componente, las conexiones entre ellos y la lista de lo que NO se pudo
mapear.

Decisión de diseño: el mapeo es DETERMINISTA, a partir de los términos
``matches`` del catálogo. No llama al LLM. Tres razones:

1. Reproducibilidad. En la demo el mismo proyecto tiene que dar el mismo
   diagrama; con un modelo de por medio no se puede prometer eso.
2. Auditable. Cada decisión queda con el término exacto que la disparó
   (``MappedComponent.reason``), así que se puede explicar por qué
   "Base de datos PostgreSQL" terminó en RDS.
3. No se cae. El generador de propuestas ya tiene que lidiar con modelos
   que devuelven vacío; el diagrama de despliegue no depende de eso.

Lo que no matchea NO se inventa: se devuelve en ``unmapped`` y la interfaz
lo muestra, que es más honesto que colocar un servicio al azar. Para cubrir
un caso nuevo se agregan términos al YAML del catálogo, no código aquí.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from app.core.cloud_catalog import (
    CloudProvider,
    CloudService,
    get_provider,
    normalize,
)

_LOGGER = logging.getLogger(__name__)

# Etiquetas que no son componentes desplegables: encabezados de subgrafo,
# notas y actores externos. Se descartan antes de mapear para no ensuciar
# el diagrama con cajas que no son infraestructura.
_NOT_A_COMPONENT = {
    "usuario",
    "usuarios",
    "cliente",
    "clientes",
    "actor",
    "navegador",
    "browser",
    "internet",
    "externo",
    "sistema externo",
    "arquitectura",
    "sistema",
    "leyenda",
}

# Longitud máxima de una etiqueta para considerarla el nombre de un
# componente. Por encima suele ser una nota o una frase suelta dentro del
# diagrama, no una caja.
_MAX_LABEL_WORDS = 10

# Piezas que NO se despliegan en la nube elegida porque son de un tercero:
# se consumen por API. No hay ningún servicio de AWS que "sea" Stripe, así
# que listarlas como "sin equivalente" daba a entender un problema donde
# solo hay una dependencia externa. Se dibujan en su propia columna.
#
# Se comparan sobre el texto normalizado del componente.
_EXTERNAL_PATTERNS: tuple[str, ...] = (
    r"\bexterno?s?\b",
    r"\bexterna?s?\b",
    r"\bterceros?\b",
    r"\bpasarela de pagos?\b",
    r"\bpasarela\b",
    r"\bstripe\b",
    r"\bpaypal\b",
    r"\bpayu\b",
    r"\bmercado ?pago\b",
    r"\bwompi\b",
    r"\btwilio\b",
    r"\bsendgrid\b",
    r"\bmailchimp\b",
    r"\bfirebase\b",
    r"\bgoogle maps\b",
    r"\bapi de un tercero\b",
    r"\bpasarela de pago\b",
    r"\bproveedor externo\b",
)
_EXTERNAL_RE = re.compile("|".join(_EXTERNAL_PATTERNS))


def is_external_service(label: str) -> bool:
    """¿La etiqueta nombra un servicio de un tercero, no desplegable?"""
    return bool(_EXTERNAL_RE.search(normalize(label)))


# --------------------------------------------------------------------------
# Lectura del Mermaid
# --------------------------------------------------------------------------

# Definición de nodo: ID seguido de la etiqueta entre cualquiera de los
# delimitadores que acepta Mermaid ([ ], ( ), (( )), { }, [( )], {{ }},
# [/ /], > ]). Se captura el id y el interior en crudo.
_NODE_RE = re.compile(
    r"""
    (?P<id>[A-Za-z_][\w-]*)          # identificador del nodo
    \s*
    (?:
        \[\(  (?P<cyl>[^\]]*?) \)\]  # [( base de datos )]
      | \(\(  (?P<circ>[^)]*?) \)\)  # (( círculo ))
      | \{\{  (?P<hex>[^}]*?) \}\}   # {{ hexágono }}
      | \[/   (?P<par>[^\]]*?) /\]   # [/ paralelogramo /]
      | \[    (?P<rect>[^\]]*?) \]   # [ rectángulo ]
      | \(    (?P<round>[^)]*?) \)   # ( redondeado )
      | \{    (?P<rhomb>[^}]*?) \}   # { rombo }
    )
    """,
    re.VERBOSE,
)

# Arista: origen, flecha, destino. Cubre -->, ---, -.->, ==> y la forma con
# etiqueta -->|texto|. Se aplica SOBRE la línea ya sin etiquetas de nodo (ver
# `_strip_node_labels`): sin ese paso, `A[Uno] --> B[Dos]` no matchea, porque
# antes de la flecha está el `]` y no el identificador.
_EDGE_RE = re.compile(
    r"(?P<src>[A-Za-z_][\w-]*)\s*"
    r"(?:-{2,3}>|-{3}|-\.-+>|={2,3}>)"
    r"\s*(?:\|[^|]*\|\s*)?"
    r"(?P<dst>[A-Za-z_][\w-]*)"
)

# Arista con la etiqueta en medio del guion: A -- texto --> B
_EDGE_MID_LABEL_RE = re.compile(
    r"(?P<src>[A-Za-z_][\w-]*)\s*-{2}\s*[^->|]+?\s*-{1,2}>\s*(?P<dst>[A-Za-z_][\w-]*)"
)

_MERMAID_KEYWORDS = {
    "graph",
    "flowchart",
    "subgraph",
    "end",
    "classdef",
    "class",
    "style",
    "linkstyle",
    "direction",
    "click",
    "sequencediagram",
    "participant",
}


def _clean_label(raw: str) -> str:
    """Quita comillas, etiquetas HTML y espacios sobrantes de una etiqueta."""
    text = (raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def parse_mermaid_nodes(mermaid: str) -> dict[str, str]:
    """``{id_del_nodo: etiqueta}`` del Mermaid.

    Solo mira líneas que no sean directivas (graph, subgraph, style...),
    porque ``style A fill:#fff`` también encaja con el patrón de nodo.
    """
    nodes: dict[str, str] = {}
    for line in (mermaid or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        first_word = stripped.split(None, 1)[0].lower().rstrip(":")
        if first_word in _MERMAID_KEYWORDS:
            # `subgraph Nombre[Etiqueta]` sí define una caja, pero es un
            # agrupador, no un componente desplegable.
            continue
        for match in _NODE_RE.finditer(stripped):
            label = next(
                (
                    value
                    for key, value in match.groupdict().items()
                    if key != "id" and value is not None
                ),
                None,
            )
            if label is None:
                continue
            cleaned = _clean_label(label)
            if cleaned:
                # Se queda con la PRIMERA definición: en Mermaid la etiqueta
                # se declara una vez y después el nodo se referencia pelado.
                nodes.setdefault(match.group("id"), cleaned)
    return nodes


def _strip_node_labels(line: str) -> str:
    """Deja solo los identificadores: ``A[Uno] --> B[Dos]`` -> ``A --> B``.

    Mermaid solo escribe la etiqueta la PRIMERA vez que aparece un nodo, así
    que sin este paso las flechas se leían bien en los diagramas largos (donde
    el origen ya venía pelado) y se perdían en los cortos, donde ambos
    extremos traen su etiqueta. Además, una etiqueta con guiones o flechas
    dentro ("Carga -> proceso") podría parecer una arista.
    """
    return _NODE_RE.sub(lambda match: match.group("id"), line)


def parse_mermaid_edges(mermaid: str) -> list[tuple[str, str]]:
    """Pares ``(origen, destino)`` de las flechas del Mermaid."""
    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in (mermaid or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        if stripped.split(None, 1)[0].lower() in _MERMAID_KEYWORDS:
            continue
        stripped = _strip_node_labels(stripped)
        for regex in (_EDGE_MID_LABEL_RE, _EDGE_RE):
            for match in regex.finditer(stripped):
                pair = (match.group("src"), match.group("dst"))
                if pair not in seen:
                    seen.add(pair)
                    edges.append(pair)
    return edges


# --------------------------------------------------------------------------
# Lectura de la sección "Componentes" de la propuesta
# --------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(?P<body>.+)$")
_COMPONENTS_HEADING_RE = re.compile(r"^\s*#{1,4}\s*.*componentes", re.IGNORECASE)
_ANY_HEADING_RE = re.compile(r"^\s*#{1,4}\s")


def parse_proposal_components(markdown: str) -> list[str]:
    """Nombres de los componentes listados en la sección "Componentes".

    Se queda con el texto en negrita del inicio del bullet (``- **Backend
    API**: expone...``) o, si no hay negrita, con lo que va antes de los dos
    puntos. Es el formato que impone el generador de propuestas.
    """
    names: list[str] = []
    inside = False
    for line in (markdown or "").splitlines():
        if _COMPONENTS_HEADING_RE.match(line):
            inside = True
            continue
        if inside and _ANY_HEADING_RE.match(line):
            break
        if not inside:
            continue
        bullet = _BULLET_RE.match(line)
        if not bullet:
            continue
        body = bullet.group("body").strip()
        bold = re.match(r"\*\*(?P<name>[^*]+)\*\*", body)
        if bold:
            name = bold.group("name")
        else:
            name = body.split(":", 1)[0]
        name = _clean_label(name).rstrip(":").strip()
        if name and name not in names:
            names.append(name)
    return names


# --------------------------------------------------------------------------
# Mapeo
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MappedComponent:
    """Un componente de la arquitectura y el servicio donde se despliega."""

    component: str
    service: CloudService
    # Término del catálogo que disparó el match; queda a la vista para poder
    # explicar (y corregir) el mapeo.
    reason: str

    @property
    def node_ids(self) -> tuple[str, ...]:  # pragma: no cover - ver DeploymentPlan
        return ()


@dataclass(frozen=True)
class ExternalService:
    """Servicio de un tercero: se consume por API, no se despliega.

    Tiene ``id`` propio para poder dibujarle flechas desde el cómputo, igual
    que a un servicio de la nube.
    """

    id: str
    name: str


@dataclass(frozen=True)
class DeploymentPlan:
    provider: CloudProvider
    components: tuple[MappedComponent, ...]
    # Conexiones entre servicios, ya validadas contra `connects_to`.
    connections: tuple[tuple[str, str], ...]
    # Componentes de la arquitectura sin servicio equivalente.
    unmapped: tuple[str, ...]
    # Conexiones del diagrama aprobado que el proveedor no permite tal cual.
    dropped_connections: tuple[tuple[str, str], ...] = ()
    # Servicios que NO salen de un componente: los puso el proveedor para
    # poder unir dos piezas que en esa nube no se conectan directamente
    # (p. ej. el balanceador entre la CDN y los contenedores).
    bridges: tuple[CloudService, ...] = ()
    # Piezas de terceros (pasarelas de pago, APIs externas): se consumen,
    # no se despliegan. Van en su propia columna del diagrama.
    externals: tuple[ExternalService, ...] = ()

    @property
    def services(self) -> list[CloudService]:
        """Servicios únicos, en el orden en que aparecen. Los puentes van al
        final: no corresponden a ningún componente de la arquitectura."""
        out: list[CloudService] = []
        for mapped in self.components:
            if mapped.service.id not in {s.id for s in out}:
                out.append(mapped.service)
        for bridge in self.bridges:
            if bridge.id not in {s.id for s in out}:
                out.append(bridge)
        return out

    def components_for(self, service_id: str) -> list[str]:
        return [m.component for m in self.components if m.service.id == service_id]


def _score(label: str, service: CloudService) -> tuple[int, str] | None:
    """Puntaje de un servicio para una etiqueta, o ``None`` si no aplica.

    Gana el término más largo que aparezca en la etiqueta: "base de datos
    relacional" debe pesar más que "bd". El `weight` del catálogo solo
    desempata entre términos de la misma longitud, para que los servicios
    por defecto de cada categoría ganen a los especializados.
    """
    normalized = f" {normalize(label)} "
    best: tuple[int, str] | None = None
    for term in service.matches:
        if not term:
            continue
        # Con espacios alrededor para no matchear dentro de otra palabra
        # ("api" no debe dispararse con "rapido").
        if f" {term} " not in normalized:
            continue
        candidate = (len(term), term)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    return best


def _best_service(label: str, provider: CloudProvider) -> tuple[CloudService, str] | None:
    best: tuple[int, int, CloudService, str] | None = None
    for service in provider.services:
        scored = _score(label, service)
        if scored is None:
            continue
        length, term = scored
        candidate = (length, service.weight, service, term)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return None
    return best[2], best[3]


def _find_bridge(
    src_id: str,
    dst_id: str,
    *,
    allowed: set[tuple[str, str]],
    provider: CloudProvider,
    preferred: set[str],
) -> Optional[CloudService]:
    """Servicio intermedio que permite unir ``src`` con ``dst`` en un salto.

    La arquitectura puede conectar dos piezas que en la nube no se hablan
    directamente: el frontend con el backend, por ejemplo. En AWS eso no es
    "CloudFront -> ECS", es "CloudFront -> balanceador -> ECS". En vez de
    descartar la flecha (perdiendo información de la arquitectura aprobada)
    o de dibujar una conexión que no existe, se busca el intermediario que
    el catálogo sí permite.

    Prioridad: un servicio que YA esté en el despliegue (no agrega cajas),
    y si no, el de mayor `weight`, que es el más típico de su categoría.
    """
    candidates = [
        service
        for service in provider.services
        if service.id not in (src_id, dst_id)
        and (src_id, service.id) in allowed
        and (service.id, dst_id) in allowed
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s.id in preferred, s.weight))


def _collapse_variants(labels: list[str]) -> list[str]:
    """Quita las variantes de un mismo componente, dejando la más informativa.

    El mismo componente llega dos veces con distinto detalle: del diagrama
    ("Pasarela de pagos") y de la sección Componentes de la propuesta
    ("Pasarela de pagos (Stripe)"). Como no son idénticos, la deduplicación
    por nombre no los junta y el aviso de "sin equivalente" los listaba los
    dos, pareciendo el doble de problemas de los que hay.

    Se conserva la etiqueta más larga: la que trae el paréntesis explicativo.
    """
    normalized = {label: normalize(label) for label in labels}
    out: list[str] = []
    for label in labels:
        mine = normalized[label]
        if not mine:
            continue
        # Hay otra etiqueta que dice lo mismo y además algo más.
        if any(
            other != label and mine != normalized[other] and mine in normalized[other]
            for other in labels
        ):
            continue
        if label not in out:
            out.append(label)
    return out


def _is_component(label: str) -> bool:
    normalized = normalize(label)
    if not normalized or normalized in _NOT_A_COMPONENT:
        return False
    return len(normalized.split()) <= _MAX_LABEL_WORDS


def build_plan(
    *,
    provider_id: str,
    mermaid: Optional[str],
    proposal_markdown: Optional[str] = None,
) -> DeploymentPlan:
    """Plan de despliegue para la arquitectura aprobada.

    Los componentes salen del Mermaid aprobado (que es LA arquitectura que
    el usuario aprobó) y se completan con la sección "Componentes" de la
    propuesta, por si el diagrama dejó alguno fuera.

    Las conexiones salen de las flechas del Mermaid: el despliegue refleja
    la arquitectura aprobada, no una topología inventada. Una flecha que el
    proveedor no permite entre esos dos servicios se descarta y se reporta
    en ``dropped_connections`` en vez de dibujarse.
    """
    provider = get_provider(provider_id)

    nodes = parse_mermaid_nodes(mermaid or "")
    edges = parse_mermaid_edges(mermaid or "")

    # node_id -> servicio, para traducir las aristas después.
    node_service: dict[str, CloudService] = {}
    components: list[MappedComponent] = []
    unmapped: list[str] = []
    seen_labels: set[str] = set()

    # Los externos se recogen como etiquetas y solo al final se juntan las
    # variantes del mismo servicio ("Pasarela de pagos" / "Pasarela de pagos
    # (Stripe)") y se les da id. Asignarlo al vuelo creaba una caja por cada
    # forma de nombrarlo.
    external_labels: list[str] = []
    node_external_label: dict[str, str] = {}

    def consider(label: str, node_id: Optional[str]) -> None:
        normalized = normalize(label)
        if not _is_component(label) or normalized in seen_labels:
            # Aun si ya se vio la etiqueta, el nodo nuevo tiene que apuntar
            # al mismo servicio para que sus flechas se traduzcan.
            if node_id and normalized in seen_labels:
                existing = next(
                    (m.service for m in components if normalize(m.component) == normalized),
                    None,
                )
                if existing is not None:
                    node_service[node_id] = existing
                else:
                    same = next(
                        (e for e in external_labels if normalize(e) == normalized), None
                    )
                    if same is not None:
                        node_external_label[node_id] = same
            return
        seen_labels.add(normalized)
        # Lo de terceros se mira ANTES de buscar servicio: "Pasarela de pagos
        # (Stripe)" contiene "pagos" y podría engancharse con algún término
        # del catálogo, y lo correcto es que salga como externo.
        if is_external_service(label):
            if label not in external_labels:
                external_labels.append(label)
            if node_id:
                node_external_label[node_id] = label
            return
        match = _best_service(label, provider)
        if match is None:
            unmapped.append(label)
            return
        service, term = match
        components.append(MappedComponent(component=label, service=service, reason=term))
        if node_id:
            node_service[node_id] = service

    for node_id, label in nodes.items():
        consider(label, node_id)
    for label in parse_proposal_components(proposal_markdown or ""):
        consider(label, None)

    # Se juntan las variantes y se les asigna id. Cada etiqueta original
    # apunta al servicio que la representa, para que las flechas de sus
    # nodos lleguen a la caja correcta.
    kept_labels = _collapse_variants(external_labels)
    externals = [
        ExternalService(id=f"ext-{index + 1}", name=label)
        for index, label in enumerate(kept_labels)
    ]
    by_label: dict[str, ExternalService] = {}
    for label in external_labels:
        mine = normalize(label)
        match_ext = next(
            (e for e in externals if mine == normalize(e.name) or mine in normalize(e.name)),
            None,
        )
        if match_ext is not None:
            by_label[label] = match_ext
    node_external = {
        node_id: by_label[label]
        for node_id, label in node_external_label.items()
        if label in by_label
    }

    # --- conexiones ---------------------------------------------------------
    allowed: set[tuple[str, str]] = set()
    for service in provider.services:
        for target in service.connects_to:
            allowed.add((service.id, target))

    chosen_ids = {m.service.id for m in components}
    connections: list[tuple[str, str]] = []
    dropped: list[tuple[str, str]] = []
    bridges: list[CloudService] = []
    seen_pairs: set[tuple[str, str]] = set()

    def add(pair: tuple[str, str]) -> None:
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            connections.append(pair)

    for src_id, dst_id in edges:
        src = node_service.get(src_id)
        dst = node_service.get(dst_id)

        # Una punta en un servicio de un tercero: la llamada siempre sale de
        # lo nuestro hacia él, así que la flecha va en esa dirección sin
        # consultar `connects_to` (el catálogo describe la nube, no a Stripe).
        src_ext, dst_ext = node_external.get(src_id), node_external.get(dst_id)
        if src_ext is not None or dst_ext is not None:
            nuestro = dst if src_ext is not None else src
            tercero = src_ext if src_ext is not None else dst_ext
            if nuestro is not None and tercero is not None:
                add((nuestro.id, tercero.id))
            continue

        if src is None or dst is None or src.id == dst.id:
            continue
        pair = (src.id, dst.id)
        if pair in seen_pairs or pair in {(b, a) for a, b in seen_pairs}:
            continue
        if pair in allowed:
            add(pair)
        elif (dst.id, src.id) in allowed:
            # La arquitectura dibujó la flecha al revés de como fluye en la
            # nube (p. ej. la base "apunta" al backend). Se endereza.
            add((dst.id, src.id))
        else:
            bridge = _find_bridge(src.id, dst.id, allowed=allowed, provider=provider, preferred=chosen_ids)
            if bridge is None:
                dropped.append(pair)
                continue
            # El puente es parte del despliegue real aunque no sea un
            # componente de la arquitectura: se agrega al diagrama.
            if bridge.id not in chosen_ids and bridge.id not in {b.id for b in bridges}:
                bridges.append(bridge)
            add((src.id, bridge.id))
            add((bridge.id, dst.id))

    # Sin flechas utilizables (diagrama sin aristas, o todas descartadas) el
    # diagrama quedaría como cajas sueltas: se completa con las conexiones
    # que el catálogo sí permite entre los servicios elegidos.
    if not connections:
        for src_id, dst_id in sorted(allowed):
            if src_id in chosen_ids and dst_id in chosen_ids:
                connections.append((src_id, dst_id))

    # Un tercero sin flecha queda flotando, como si no formara parte del
    # sistema. Pasa cuando la pieza sale de la sección Componentes de la
    # propuesta y no de un nodo del diagrama: no hay arista que traducir.
    # Quien llama a un servicio externo es siempre el cómputo, así que se
    # conecta desde el servicio de cómputo principal (el de mayor `weight`
    # entre los elegidos, que es el que aloja el backend).
    if externals:
        compute = [
            m.service
            for m in components
            if m.service.category == "compute"
        ]
        main_compute = max(compute, key=lambda s: s.weight) if compute else None
        if main_compute is not None:
            for external in externals:
                if not any(dst == external.id for _src, dst in connections):
                    add((main_compute.id, external.id))

    unmapped = _collapse_variants(unmapped)

    if unmapped:
        _LOGGER.info(
            "Despliegue %s: %d componente(s) sin servicio equivalente: %s",
            provider.id,
            len(unmapped),
            ", ".join(unmapped),
        )

    return DeploymentPlan(
        provider=provider,
        components=tuple(components),
        connections=tuple(connections),
        unmapped=tuple(unmapped),
        dropped_connections=tuple(dropped),
        bridges=tuple(bridges),
        externals=tuple(externals),
    )


def plan_to_dict(plan: DeploymentPlan) -> dict:
    """Forma serializable del plan, para la API y para guardar en el mensaje."""
    return {
        "provider": {
            "id": plan.provider.id,
            "name": plan.provider.name,
            "short_name": plan.provider.short_name,
            "color": plan.provider.color,
            "docs_url": plan.provider.docs_url,
        },
        "components": [
            {
                "component": m.component,
                "service_id": m.service.id,
                "service_name": m.service.name,
                "category": m.service.category,
                "category_label": m.service.category_label,
                "summary": m.service.summary,
                "deploy_note": m.service.deploy_note,
                "matched_term": m.reason,
            }
            for m in plan.components
        ],
        "connections": [{"from": a, "to": b} for a, b in plan.connections],
        "bridges": [
            {
                "service_id": s.id,
                "service_name": s.name,
                "category": s.category,
                "category_label": s.category_label,
                "deploy_note": s.deploy_note,
            }
            for s in plan.bridges
        ],
        "externals": [{"id": e.id, "name": e.name} for e in plan.externals],
        "unmapped": list(plan.unmapped),
        "dropped_connections": [{"from": a, "to": b} for a, b in plan.dropped_connections],
    }
