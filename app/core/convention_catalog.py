"""Catálogo de convenciones de estructura de repositorio (data/conventions/*.yaml).

Es el equivalente de ``app/core/cloud_catalog.py`` para la HU del árbol de
carpetas: lee los YAML, los valida al cargar y expone una vista tipada para
que el generador del árbol no tenga que conocer la forma del archivo.

Dos decisiones que conviene no deshacer:

1. **Un archivo roto no tumba a los demás.** Si una convención no valida, se
   registra el error y se omite; las otras siguen disponibles. Un YAML mal
   editado no debe dejar la aplicación sin la funcionalidad completa.

2. **Toda ruta del árbol lleva su fuente.** Cada nodo declara ``source``, el
   índice 1-based dentro de ``fuentes`` del propio archivo, y la carga
   verifica que el índice exista. Así es imposible que una línea del árbol
   llegue a la interfaz o al ADR sin respaldo: si falta la fuente, la
   convención no carga y se dice por qué.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

logger = logging.getLogger(__name__)

CONVENTIONS_DIR = Path(__file__).resolve().parents[2] / "data" / "conventions"

# Capa del proyecto que organiza la convención. Un proyecto puede combinar una
# de cada capa (FastAPI para el backend y React para el frontend).
LAYERS: tuple[str, ...] = ("backend", "frontend")

# Roles que puede ocupar un nodo del árbol. Es el vocabulario compartido entre
# las convenciones (que declaran dónde va cada rol) y los patrones (que
# declaran qué rol aportan). Si un patrón declara un rol que no está acá, la
# carga del patrón avisa y el aporte se ignora: antes que ubicar algo en una
# carpeta inventada, se prefiere decir que no se pudo ubicar.
ROLES: tuple[str, ...] = (
    "api",
    "service",
    "repository",
    "unit_of_work",
    "dto",
    "domain",
    "port",
    "adapter",
    "integration",
    "worker",
    "ui",
    "tests",
)

_NON_WORD = re.compile(r"[^a-z0-9]+")


class ConventionCatalogError(RuntimeError):
    """Un YAML de convención no cumple el esquema."""


@dataclass(frozen=True)
class TreeNode:
    """Una línea del árbol, con la fuente que la respalda."""

    path: str
    note: str
    source_title: str
    source_url: str
    role: str | None = None

    def rendered(self, **values: str) -> str:
        """La ruta con los marcadores reemplazados."""
        rendered = self.path
        for key, value in values.items():
            rendered = rendered.replace("{" + key + "}", value)
        return rendered


@dataclass(frozen=True)
class Convention:
    convention_id: str
    name: str
    layer: str
    matches: tuple[str, ...]
    weight: int
    summary: str
    nesting_limit: int | None
    base_tree: tuple[TreeNode, ...]
    module_tree: tuple[TreeNode, ...]
    pattern_slot: str
    pattern_slot_note: str
    pattern_slot_source_title: str
    pattern_slot_source_url: str
    documented_roles: frozenset[str]
    fuentes: tuple[dict[str, str], ...] = field(default=())


def normalize(text: str) -> str:
    """Minúsculas, sin tildes y con los separadores colapsados a un espacio.

    Misma función que en el catálogo de nube y por la misma razón: los
    términos de ``matches`` están normalizados y lo que escribe el LLM en las
    tecnologías de la propuesta puede venir con tildes, mayúsculas o guiones.
    """
    lowered = (text or "").lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", stripped).strip()


def _require(raw: dict, key: str, where: str) -> Any:
    if key not in raw or raw[key] in (None, ""):
        raise ConventionCatalogError(f"{where}: falta el campo obligatorio '{key}'")
    return raw[key]


def _parse_fuentes(raw: Any, *, where: str) -> tuple[dict[str, str], ...]:
    if not isinstance(raw, list) or not raw:
        raise ConventionCatalogError(f"{where}: 'fuentes' debe ser una lista no vacía")
    fuentes: list[dict[str, str]] = []
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ConventionCatalogError(f"{where}: fuente {position} no es un mapa")
        titulo = str(item.get("titulo") or "").strip()
        url = str(item.get("url") or "").strip()
        if not titulo or not url:
            raise ConventionCatalogError(
                f"{where}: la fuente {position} necesita 'titulo' y 'url'"
            )
        fuentes.append({"titulo": titulo, "url": url})
    return tuple(fuentes)


def _resolve_source(
    index: Any, fuentes: tuple[dict[str, str], ...], *, where: str
) -> dict[str, str]:
    """``source: N`` -> la fuente N (1-based). Falla si el índice no existe."""
    if not isinstance(index, int) or isinstance(index, bool):
        raise ConventionCatalogError(f"{where}: 'source' debe ser un entero 1-based")
    if not 1 <= index <= len(fuentes):
        raise ConventionCatalogError(
            f"{where}: 'source: {index}' no existe; hay {len(fuentes)} fuente(s)"
        )
    return fuentes[index - 1]


def _parse_tree(
    raw: Any,
    fuentes: tuple[dict[str, str], ...],
    *,
    where: str,
    required: bool,
) -> tuple[TreeNode, ...]:
    if raw in (None, []):
        if required:
            raise ConventionCatalogError(f"{where}: no puede estar vacío")
        return ()
    if not isinstance(raw, list):
        raise ConventionCatalogError(f"{where}: debe ser una lista")
    nodes: list[TreeNode] = []
    for position, item in enumerate(raw, start=1):
        node_where = f"{where}[{position}]"
        if not isinstance(item, dict):
            raise ConventionCatalogError(f"{node_where}: no es un mapa")
        path = str(_require(item, "path", node_where)).strip()
        fuente = _resolve_source(item.get("source"), fuentes, where=node_where)
        role = item.get("role")
        if role is not None:
            role = str(role).strip()
            if role not in ROLES:
                raise ConventionCatalogError(
                    f"{node_where}: rol '{role}' desconocido; válidos: {', '.join(ROLES)}"
                )
        nodes.append(
            TreeNode(
                path=path,
                note=" ".join(str(item.get("note") or "").split()),
                source_title=fuente["titulo"],
                source_url=fuente["url"],
                role=role or None,
            )
        )
    return tuple(nodes)


def _parse_convention(raw: Any, *, source: Path) -> Convention:
    where = source.name
    if not isinstance(raw, dict):
        raise ConventionCatalogError(f"{where}: el archivo no contiene un mapa")

    convention_id = str(_require(raw, "convention_id", where)).strip()
    if normalize(convention_id).replace(" ", "_") != convention_id.replace("-", "_"):
        # Se usa como clave en la base y en la URL de la API: sin tildes,
        # espacios ni mayúsculas.
        raise ConventionCatalogError(
            f"{where}: 'convention_id' debe ser minúsculas sin tildes ni espacios"
        )

    layer = str(_require(raw, "layer", where)).strip()
    if layer not in LAYERS:
        raise ConventionCatalogError(
            f"{where}: 'layer' debe ser uno de {', '.join(LAYERS)}"
        )

    fuentes = _parse_fuentes(raw.get("fuentes"), where=where)

    matches_raw = raw.get("matches") or []
    if not isinstance(matches_raw, list) or not matches_raw:
        raise ConventionCatalogError(f"{where}: 'matches' debe ser una lista no vacía")
    matches = tuple(sorted({normalize(str(m)) for m in matches_raw if str(m).strip()}))
    if not matches:
        raise ConventionCatalogError(f"{where}: 'matches' quedó vacío al normalizar")

    nesting_limit = raw.get("nesting_limit")
    if nesting_limit is not None:
        if not isinstance(nesting_limit, int) or isinstance(nesting_limit, bool):
            raise ConventionCatalogError(f"{where}: 'nesting_limit' debe ser entero o null")
        if nesting_limit < 1:
            raise ConventionCatalogError(f"{where}: 'nesting_limit' debe ser >= 1")

    pattern_slot = str(_require(raw, "pattern_slot", where)).strip()
    slot_fuente = _resolve_source(
        raw.get("pattern_slot_source"), fuentes, where=f"{where}.pattern_slot_source"
    )

    documented = raw.get("documented_roles") or []
    if not isinstance(documented, list):
        raise ConventionCatalogError(f"{where}: 'documented_roles' debe ser una lista")
    for role in documented:
        if str(role) not in ROLES:
            raise ConventionCatalogError(
                f"{where}: rol documentado '{role}' desconocido"
            )

    return Convention(
        convention_id=convention_id,
        name=str(_require(raw, "name", where)).strip(),
        layer=layer,
        matches=matches,
        weight=int(raw.get("weight") or 50),
        summary=" ".join(str(raw.get("summary") or "").split()),
        nesting_limit=nesting_limit,
        base_tree=_parse_tree(
            raw.get("base_tree"), fuentes, where=f"{where}.base_tree", required=True
        ),
        module_tree=_parse_tree(
            raw.get("module_tree"), fuentes, where=f"{where}.module_tree", required=True
        ),
        pattern_slot=pattern_slot,
        pattern_slot_note=" ".join(str(raw.get("pattern_slot_note") or "").split()),
        pattern_slot_source_title=slot_fuente["titulo"],
        pattern_slot_source_url=slot_fuente["url"],
        documented_roles=frozenset(str(r) for r in documented),
        fuentes=fuentes,
    )


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Convention]:
    """``{convention_id: Convention}``; omite (con log) los archivos inválidos."""
    catalog: dict[str, Convention] = {}
    if not CONVENTIONS_DIR.is_dir():
        logger.warning("No existe el directorio de convenciones: %s", CONVENTIONS_DIR)
        return catalog
    for path in sorted(CONVENTIONS_DIR.glob("*.yaml")):
        try:
            convention = _parse_convention(
                yaml.safe_load(path.read_text(encoding="utf-8")), source=path
            )
        except (ConventionCatalogError, yaml.YAMLError) as exc:
            logger.error("Convención inválida en %s: %s", path.name, exc)
            continue
        if convention.convention_id in catalog:
            logger.error(
                "convention_id duplicado '%s' en %s; se conserva el primero",
                convention.convention_id,
                path.name,
            )
            continue
        catalog[convention.convention_id] = convention
    return catalog


def reset_catalog_cache() -> None:
    """Para las pruebas, que escriben YAML temporales."""
    load_catalog.cache_clear()


def list_conventions() -> list[Convention]:
    return list(load_catalog().values())


def get_convention(convention_id: str) -> Convention:
    try:
        return load_catalog()[convention_id]
    except KeyError:
        raise ConventionCatalogError(
            f"No existe la convención '{convention_id}'"
        ) from None


def match_convention(terms: Iterable[str], *, layer: str) -> tuple[Convention | None, str]:
    """La convención de ``layer`` que mejor matchea, y el término que la activó.

    Gana el término más largo (más específico): "spring boot" le gana a
    "spring". A igual longitud, el mayor ``weight``. Devuelve ``(None, "")``
    cuando ninguna convención de esa capa matchea, que es un resultado
    legítimo: el generador lo reporta en lugar de elegir una al azar.
    """
    haystack = " ".join(normalize(t) for t in terms if t)
    if not haystack:
        return None, ""
    best: tuple[Convention, str] | None = None
    best_key: tuple[int, int] = (-1, -1)
    for convention in load_catalog().values():
        if convention.layer != layer:
            continue
        for term in convention.matches:
            if term and term in haystack:
                key = (len(term), convention.weight)
                if key > best_key:
                    best_key = key
                    best = (convention, term)
    if best is None:
        return None, ""
    return best[0], best[1]


def catalog_documents() -> Iterable[tuple[str, str, dict]]:
    """``(clave, texto, metadatos)`` por convención, para indexar en el RAG.

    Mismo contrato que ``cloud_catalog.catalog_documents`` para que
    ``scripts/seed_conventions.py`` sea tan corto como el de la nube.
    """
    for convention in load_catalog().values():
        lineas = [f"{convention.name}: {convention.summary}"]
        lineas.append(
            "Estructura base: "
            + "; ".join(f"{n.path} ({n.note})" for n in convention.base_tree)
        )
        lineas.append(
            "Estructura por módulo: "
            + "; ".join(f"{n.path} ({n.note})" for n in convention.module_tree)
        )
        if convention.nesting_limit:
            lineas.append(
                f"La fuente recomienda no pasar de {convention.nesting_limit} "
                "niveles de carpetas anidadas."
            )
        texto = " ".join(" ".join(linea.split()) for linea in lineas)
        yield (
            convention.convention_id,
            texto,
            {
                "convention_id": convention.convention_id,
                "name": convention.name,
                "layer": convention.layer,
                "matches": list(convention.matches),
                "nesting_limit": convention.nesting_limit,
                "fuentes": [dict(f) for f in convention.fuentes],
            },
        )
