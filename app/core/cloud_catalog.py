"""
Catálogo de servicios de nube (HU: diagrama de despliegue).

Carga `data/cloud/<proveedor>.yaml` y los íconos de
`data/cloud/icons/<proveedor>/<id>.png`.

Es un catálogo APARTE de la base de patrones: los patrones viven en
``architect_patterns`` (PostgreSQL) y se consultan por embeddings; esto es
un archivo versionado en el repo, porque el mapeo "componente -> servicio"
tiene que ser reproducible y auditable para la demo, no estadístico. Lo que
sí entra al RAG es una copia textual del catálogo, bajo su propia categoría
(ver ``scripts/seed_cloud_catalog.py``).

El catálogo se lee una vez y se cachea: son dos archivos pequeños y no
cambian en caliente.
"""

from __future__ import annotations

import base64
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

_LOGGER = logging.getLogger(__name__)

# data/ está en la raíz del proyecto, dos niveles por encima de app/core/.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLOUD_DATA_DIR = _PROJECT_ROOT / "data" / "cloud"
ICONS_DIR = CLOUD_DATA_DIR / "icons"

# Categorías conocidas. No es una lista cerrada por capricho: el diagrama
# pinta un color por categoría y el mapeo compara categorías entre nubes,
# así que una categoría nueva sin registrar saldría en gris y no tendría
# equivalencia entre proveedores.
CATEGORIES: tuple[str, ...] = (
    "compute",
    "database",
    "cache",
    "storage",
    "queue",
    "cdn",
    "loadbalancer",
    "dns",
    "apigateway",
    "auth",
    "secrets",
    "monitoring",
    "network",
    "cicd",
)

# Color por categoría (fondo de la tarjeta en el diagrama). Tonos suaves
# para que el ícono oficial siga siendo lo que más resalta.
CATEGORY_COLORS: dict[str, str] = {
    "compute": "#EEF2FF",
    "database": "#ECFDF5",
    "cache": "#FEF3C7",
    "storage": "#F0F9FF",
    "queue": "#FDF4FF",
    "cdn": "#F0FDFA",
    "loadbalancer": "#F0FDFA",
    "dns": "#F0FDFA",
    "apigateway": "#F0FDFA",
    "auth": "#FEF2F2",
    "secrets": "#FEF2F2",
    "monitoring": "#F8FAFC",
    "network": "#F8FAFC",
    "cicd": "#F8FAFC",
}

CATEGORY_LABELS: dict[str, str] = {
    "compute": "Cómputo",
    "database": "Base de datos",
    "cache": "Caché",
    "storage": "Almacenamiento",
    "queue": "Mensajería",
    "cdn": "CDN",
    "loadbalancer": "Balanceador",
    "dns": "DNS",
    "apigateway": "API Gateway",
    "auth": "Autenticación",
    "secrets": "Secretos",
    "monitoring": "Observabilidad",
    "network": "Red",
    "cicd": "CI/CD",
}

DEFAULT_CATEGORY_COLOR = "#F1F5F9"


class CloudCatalogError(RuntimeError):
    """El catálogo de un proveedor está mal formado o no existe."""


@dataclass(frozen=True)
class CloudService:
    id: str
    name: str
    category: str
    tier: str
    summary: str
    deploy_note: str
    matches: tuple[str, ...]
    weight: int
    connects_to: tuple[str, ...]
    provider_id: str

    @property
    def icon_path(self) -> Path:
        return ICONS_DIR / self.provider_id / f"{self.id}.png"

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    @property
    def color(self) -> str:
        return CATEGORY_COLORS.get(self.category, DEFAULT_CATEGORY_COLOR)


@dataclass(frozen=True)
class CloudTier:
    id: str
    label: str


@dataclass(frozen=True)
class CloudProvider:
    id: str
    name: str
    short_name: str
    color: str
    accent: str
    docs_url: str
    tiers: tuple[CloudTier, ...]
    services: tuple[CloudService, ...] = field(default=())

    def service(self, service_id: str) -> Optional[CloudService]:
        return next((s for s in self.services if s.id == service_id), None)

    def by_category(self, category: str) -> list[CloudService]:
        return [s for s in self.services if s.category == category]

    @property
    def tier_order(self) -> list[str]:
        return [t.id for t in self.tiers]


# --------------------------------------------------------------------------
# Normalización de texto
# --------------------------------------------------------------------------

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes y con los separadores colapsados a un espacio.

    El mapeo compara el nombre del componente que escribió el LLM (que puede
    venir con tildes, mayúsculas, guiones o paréntesis) contra los términos
    del catálogo, que están todos normalizados. Sin esto, "Autenticación" no
    matchearía con "autenticacion".
    """
    lowered = (text or "").lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _NON_WORD.sub(" ", stripped).strip()


# --------------------------------------------------------------------------
# Carga
# --------------------------------------------------------------------------


def _require(raw: dict, key: str, where: str) -> Any:
    if key not in raw or raw[key] in (None, ""):
        raise CloudCatalogError(f"Falta '{key}' en {where}")
    return raw[key]


def _parse_service(raw: Any, *, provider_id: str) -> CloudService:
    if not isinstance(raw, dict):
        raise CloudCatalogError(
            f"Cada servicio de {provider_id} debe ser un diccionario; vino {type(raw).__name__}"
        )
    service_id = str(_require(raw, "id", f"un servicio de {provider_id}"))
    where = f"el servicio '{service_id}' de {provider_id}"
    category = str(_require(raw, "category", where))
    if category not in CATEGORIES:
        raise CloudCatalogError(
            f"Categoría desconocida '{category}' en {where}. "
            f"Las válidas son: {', '.join(CATEGORIES)}"
        )
    matches = raw.get("matches") or []
    if not isinstance(matches, list):
        raise CloudCatalogError(f"'matches' de {where} debe ser una lista")
    connects = raw.get("connects_to") or []
    if not isinstance(connects, list):
        raise CloudCatalogError(f"'connects_to' de {where} debe ser una lista")
    return CloudService(
        id=service_id,
        name=str(_require(raw, "name", where)),
        category=category,
        tier=str(raw.get("tier") or "compute"),
        summary=" ".join(str(raw.get("summary") or "").split()),
        deploy_note=" ".join(str(raw.get("deploy_note") or "").split()),
        # Se normalizan AL CARGAR, no en cada comparación: el mapeo recorre
        # todos los servicios por cada componente.
        matches=tuple(normalize(str(m)) for m in matches if str(m).strip()),
        weight=int(raw.get("weight") or 50),
        connects_to=tuple(str(c) for c in connects),
        provider_id=provider_id,
    )


def _parse_provider(raw: dict, *, source: Path) -> CloudProvider:
    provider_id = str(_require(raw, "id", source.name))
    tiers_raw = raw.get("tiers") or []
    tiers = tuple(
        CloudTier(id=str(t.get("id")), label=str(t.get("label") or t.get("id")))
        for t in tiers_raw
        if isinstance(t, dict) and t.get("id")
    )
    if not tiers:
        raise CloudCatalogError(f"{source.name} no declara 'tiers'")

    services_raw = raw.get("services") or []
    if not services_raw:
        raise CloudCatalogError(f"{source.name} no declara 'services'")
    services = tuple(_parse_service(s, provider_id=provider_id) for s in services_raw)

    seen: set[str] = set()
    for service in services:
        if service.id in seen:
            raise CloudCatalogError(f"Servicio duplicado '{service.id}' en {source.name}")
        seen.add(service.id)

    tier_ids = {t.id for t in tiers}
    for service in services:
        if service.tier not in tier_ids:
            raise CloudCatalogError(
                f"El servicio '{service.id}' de {provider_id} declara el tier "
                f"'{service.tier}', que no está en 'tiers'"
            )
        # Una conexión hacia un servicio inexistente dibujaría una flecha a
        # ninguna parte; se detecta al cargar y no en mitad de un render.
        for target in service.connects_to:
            if target not in seen:
                raise CloudCatalogError(
                    f"El servicio '{service.id}' de {provider_id} declara "
                    f"connects_to '{target}', que no existe en el catálogo"
                )

    return CloudProvider(
        id=provider_id,
        name=str(_require(raw, "name", source.name)),
        short_name=str(raw.get("short_name") or provider_id.upper()),
        color=str(raw.get("color") or "#334155"),
        accent=str(raw.get("accent") or "#0F172A"),
        docs_url=str(raw.get("docs_url") or ""),
        tiers=tiers,
        services=services,
    )


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, CloudProvider]:
    """Todos los proveedores de `data/cloud/*.yaml`, por id.

    Un archivo roto NO tumba el catálogo entero: se registra y se sigue con
    los demás, para que un error de edición en gcp.yaml no deje la demo sin
    AWS. Si no queda ninguno, ahí sí se lanza.
    """
    providers: dict[str, CloudProvider] = {}
    if not CLOUD_DATA_DIR.is_dir():
        raise CloudCatalogError(f"No existe el directorio del catálogo: {CLOUD_DATA_DIR}")

    for path in sorted(CLOUD_DATA_DIR.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            provider = _parse_provider(raw, source=path)
        except (CloudCatalogError, yaml.YAMLError) as exc:
            _LOGGER.error("Catálogo cloud inválido en %s: %s", path.name, exc)
            continue
        providers[provider.id] = provider

    if not providers:
        raise CloudCatalogError(
            f"No se pudo cargar ningún proveedor desde {CLOUD_DATA_DIR}"
        )
    return providers


def reset_catalog_cache() -> None:
    """Limpia el cache (las pruebas escriben catálogos temporales)."""
    load_catalog.cache_clear()
    _icon_data_uri.cache_clear()


def list_providers() -> list[CloudProvider]:
    return sorted(load_catalog().values(), key=lambda p: p.name)


def get_provider(provider_id: str) -> CloudProvider:
    providers = load_catalog()
    provider = providers.get((provider_id or "").strip().lower())
    if provider is None:
        raise CloudCatalogError(
            f"Proveedor '{provider_id}' no habilitado. "
            f"Disponibles: {', '.join(sorted(providers))}"
        )
    return provider


# --------------------------------------------------------------------------
# Íconos
# --------------------------------------------------------------------------

# Glifo de reserva: un servicio sin PNG sale con este cuadro gris en vez de
# romper el render. Es un SVG inline para no depender de ningún archivo.
_FALLBACK_ICON = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(
        (
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
            "<rect width='64' height='64' rx='12' fill='#CBD5E1'/>"
            "<path d='M20 26h24v4H20zm0 8h24v4H20zm0 8h16v4H20z' fill='#475569'/>"
            "</svg>"
        ).encode("utf-8")
    ).decode("ascii")
)


@lru_cache(maxsize=256)
def _icon_data_uri(provider_id: str, service_id: str) -> str:
    path = ICONS_DIR / provider_id / f"{service_id}.png"
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        _LOGGER.warning(
            "Sin ícono para %s/%s (%s); se usa el glifo de reserva.",
            provider_id,
            service_id,
            path,
        )
        return _FALLBACK_ICON
    return f"data:image/png;base64,{encoded}"


def icon_data_uri(service: CloudService) -> str:
    """El PNG del servicio como data URI.

    Va embebido porque el diagrama se renderiza en el sidecar de Puppeteer,
    que no tiene salida a internet NI acceso al disco del backend: una ruta
    de archivo o una URL externa darían un ícono roto.
    """
    return _icon_data_uri(service.provider_id, service.id)


def missing_icons() -> list[str]:
    """Servicios del catálogo que no tienen su PNG. Lo usa la prueba del
    catálogo y el script de seed para avisar temprano."""
    missing: list[str] = []
    for provider in load_catalog().values():
        for service in provider.services:
            if not service.icon_path.is_file():
                missing.append(f"{provider.id}/{service.id}")
    return sorted(missing)


def catalog_documents() -> Iterable[tuple[str, str, dict]]:
    """``(id, texto, metadatos)`` por servicio, para cargar en el RAG.

    El texto junta nombre, categoría, resumen, dónde se despliega y los
    términos que lo disparan, que es exactamente lo que necesita una
    búsqueda semántica del tipo "dónde pongo la base de datos".
    """
    for provider in list_providers():
        for service in provider.services:
            text = (
                f"{service.name} ({provider.name}). "
                f"Categoría: {service.category_label}. "
                f"{service.summary} "
                f"Dónde se despliega: {service.deploy_note} "
                f"Se usa para: {', '.join(service.matches)}."
            )
            yield (
                f"{provider.id}:{service.id}",
                " ".join(text.split()),
                {
                    "source": "cloud_catalog",
                    "provider": provider.id,
                    "provider_name": provider.name,
                    "service_id": service.id,
                    "service_name": service.name,
                    "category": service.category,
                },
            )
