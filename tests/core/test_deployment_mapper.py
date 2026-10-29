"""
Pruebas del mapeo "componente -> servicio de nube".

El mapeo es determinista a propósito (ver el docstring del módulo), así que
se puede fijar el resultado exacto: si alguien cambia los términos del
catálogo y un componente típico deja de caer donde debe, estas pruebas lo
dicen.
"""

import pytest

from app.core.deployment_mapper import (
    build_plan,
    parse_mermaid_edges,
    parse_mermaid_nodes,
    parse_proposal_components,
    plan_to_dict,
)

MERMAID = """graph TD
    U[Usuario] --> FE[Frontend React SPA]
    FE --> API[Backend API FastAPI]
    API --> DB[(Base de datos PostgreSQL)]
    API --> CACHE[Cache Redis]
    API --> COLA[Cola de mensajes]
    COLA --> WORKER[Worker de procesamiento]
    WORKER --> STORE[Almacenamiento de archivos]
"""

PROPUESTA = """## Componentes
- **Frontend React SPA**: interfaz del usuario.
- **Backend API FastAPI**: expone los endpoints.
- **Monitoreo**: métricas y registros.

## Tecnologías
- Python 3.11
"""


# --------------------------------------------------------------------------
# Lectura del Mermaid
# --------------------------------------------------------------------------


def test_lee_los_nodos_con_sus_etiquetas():
    nodos = parse_mermaid_nodes(MERMAID)
    assert nodos["FE"] == "Frontend React SPA"
    # La forma [( )] de base de datos también se reconoce.
    assert nodos["DB"] == "Base de datos PostgreSQL"


def test_lee_nodos_con_comillas_y_saltos_de_linea():
    nodos = parse_mermaid_nodes('graph TD\n  A["Servicio de<br/>pagos"] --> B[Otro]')
    assert nodos["A"] == "Servicio de pagos"


def test_ignora_las_directivas_de_estilo():
    """`style A fill:#fff` encaja con el patrón de nodo; no debe colarse."""
    nodos = parse_mermaid_nodes("graph TD\n  A[Backend]\n  style A fill:#fff\n")
    assert list(nodos) == ["A"]


def test_lee_las_flechas():
    aristas = parse_mermaid_edges(MERMAID)
    assert ("FE", "API") in aristas
    assert ("API", "DB") in aristas


@pytest.mark.parametrize(
    "linea",
    [
        "A --> B",
        "A --- B",
        "A -.-> B",
        "A ==> B",
        "A -->|guarda| B",
        "A -- guarda --> B",
    ],
)
def test_reconoce_las_formas_de_flecha(linea):
    assert ("A", "B") in parse_mermaid_edges(f"graph TD\n  {linea}\n")


def test_lee_la_flecha_aunque_los_dos_nodos_traigan_su_etiqueta():
    """Mermaid escribe la etiqueta solo la PRIMERA vez que aparece un nodo.
    En un diagrama corto los dos extremos la traen, y antes la flecha se
    perdía porque justo antes de `-->` estaba el `]` y no el identificador.
    """
    aristas = parse_mermaid_edges("graph TD\n  FE[Frontend] --> API[Backend]\n")
    assert ("FE", "API") in aristas


def test_una_etiqueta_con_guiones_no_parece_una_flecha():
    aristas = parse_mermaid_edges("graph TD\n  A[Carga --> proceso] --> B[Fin]\n")
    assert aristas == [("A", "B")]


# --------------------------------------------------------------------------
# Lectura de la propuesta
# --------------------------------------------------------------------------


def test_lee_los_componentes_de_la_propuesta():
    assert parse_proposal_components(PROPUESTA) == [
        "Frontend React SPA",
        "Backend API FastAPI",
        "Monitoreo",
    ]


def test_se_detiene_en_la_siguiente_seccion():
    """Sin el corte, "Python 3.11" entraría como componente."""
    assert "Python 3.11" not in parse_proposal_components(PROPUESTA)


# --------------------------------------------------------------------------
# Mapeo
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider_id,esperado",
    [
        (
            "aws",
            {
                "Frontend React SPA": "cloudfront",
                "Backend API FastAPI": "ecs",
                "Base de datos PostgreSQL": "rds",
                "Cache Redis": "elasticache",
                "Cola de mensajes": "sqs",
                "Worker de procesamiento": "lambda",
                "Almacenamiento de archivos": "s3",
                "Monitoreo": "cloudwatch",
            },
        ),
        (
            "gcp",
            {
                "Frontend React SPA": "cloud-cdn",
                "Backend API FastAPI": "cloud-run",
                "Base de datos PostgreSQL": "cloud-sql",
                "Cache Redis": "memorystore",
                "Cola de mensajes": "pubsub",
                "Worker de procesamiento": "functions",
                "Almacenamiento de archivos": "cloud-storage",
                "Monitoreo": "monitoring",
            },
        ),
    ],
)
def test_mapea_cada_componente_al_servicio_equivalente(provider_id, esperado):
    plan = build_plan(
        provider_id=provider_id, mermaid=MERMAID, proposal_markdown=PROPUESTA
    )
    obtenido = {m.component: m.service.id for m in plan.components}
    assert obtenido == esperado


def test_no_quedan_componentes_sin_mapear_en_el_caso_tipico():
    for provider_id in ("aws", "gcp"):
        plan = build_plan(
            provider_id=provider_id, mermaid=MERMAID, proposal_markdown=PROPUESTA
        )
        assert plan.unmapped == ()


def test_el_usuario_no_es_un_componente_desplegable():
    plan = build_plan(provider_id="aws", mermaid=MERMAID)
    assert "Usuario" not in [m.component for m in plan.components]
    assert "Usuario" not in plan.unmapped


class TestServiciosDeTerceros:
    """Stripe no se despliega, se consume. Listarlos como "sin equivalente"
    daba a entender un problema donde solo hay una dependencia externa."""

    @pytest.mark.parametrize(
        "componente",
        [
            "Pasarela de pagos (Stripe)",
            "Pasarela de pago",
            "Integración con sistema externo",
            "API externa de catálogo",
            "Servicio de un tercero",
        ],
    )
    def test_se_reconocen_como_externos(self, componente):
        plan = build_plan(
            provider_id="aws", mermaid=f"graph TD\n  A[{componente}] --> B[Backend FastAPI]\n"
        )
        assert [e.name for e in plan.externals] == [componente]
        assert plan.unmapped == ()

    def test_no_se_confunde_un_componente_propio_con_uno_externo(self):
        plan = build_plan(
            provider_id="aws", mermaid="graph TD\n  A[Base de datos PostgreSQL]\n"
        )
        assert plan.externals == ()

    def test_la_flecha_sale_de_lo_nuestro_hacia_el_tercero(self):
        """El catálogo describe la nube, no a Stripe: la dirección se decide
        por quién llama a quién, no por `connects_to`."""
        plan = build_plan(
            provider_id="aws",
            mermaid="graph TD\n  API[Backend FastAPI] --> P[Pasarela de pagos Stripe]\n",
        )
        externo = plan.externals[0]
        assert ("ecs", externo.id) in plan.connections

    def test_una_caja_por_servicio_aunque_se_nombre_de_dos_formas(self):
        """El diagrama lo nombra "Pasarela de pagos" y la propuesta
        "Pasarela de pagos (Stripe)": es el mismo tercero, no dos."""
        plan = build_plan(
            provider_id="aws",
            mermaid="graph TD\n  API[Backend FastAPI] --> P[Pasarela de pagos]\n",
            proposal_markdown="## Componentes\n- **Pasarela de pagos (Stripe)**: cobros.\n",
        )
        assert [e.name for e in plan.externals] == ["Pasarela de pagos (Stripe)"]

    def test_la_flecha_llega_a_la_caja_que_quedo(self):
        """Al juntar variantes, el nodo del diagrama tiene que apuntar al
        servicio que sobrevivió, no a uno que ya no existe."""
        plan = build_plan(
            provider_id="aws",
            mermaid="graph TD\n  API[Backend FastAPI] --> P[Pasarela de pagos]\n",
            proposal_markdown="## Componentes\n- **Pasarela de pagos (Stripe)**: cobros.\n",
        )
        destino = plan.externals[0].id
        assert ("ecs", destino) in plan.connections

    def test_un_tercero_sin_nodo_en_el_diagrama_igual_se_conecta(self):
        """Si la pieza solo aparece en la sección Componentes, no hay arista
        que traducir y la caja quedaba flotando. Quien llama a un servicio
        externo es siempre el cómputo."""
        plan = build_plan(
            provider_id="aws",
            mermaid="graph TD\n  FE[Frontend Web] --> API[API REST Django]\n",
            proposal_markdown="## Componentes\n- **Pasarela de pagos (Stripe)**: cobros.\n",
        )
        externo = plan.externals[0]
        assert ("ecs", externo.id) in plan.connections

    def test_no_duplica_la_flecha_si_el_diagrama_ya_la_tenia(self):
        plan = build_plan(
            provider_id="aws",
            mermaid="graph TD\n  API[Backend FastAPI] --> P[Pasarela de pagos]\n",
            proposal_markdown="## Componentes\n- **Pasarela de pagos (Stripe)**: cobros.\n",
        )
        hacia_externos = [c for c in plan.connections if c[1].startswith("ext-")]
        assert len(hacia_externos) == 1

    def test_viajan_en_el_plan_serializado(self):
        plan = build_plan(
            provider_id="gcp",
            mermaid="graph TD\n  A[Backend FastAPI] --> B[Pasarela de pagos Stripe]\n",
        )
        data = plan_to_dict(plan)
        assert data["externals"] and data["externals"][0]["name"]


def test_no_repite_el_mismo_componente_con_distinto_detalle():
    """El mismo componente llega del diagrama ("Motor de reglas") y de la
    propuesta ("Motor de reglas (Drools)"). Listar los dos hacía parecer
    que había el doble de problemas; se conserva el más informativo.

    El ejemplo NO es una pasarela de pagos a propósito: eso ahora se
    reconoce como servicio de un tercero y no llega a `unmapped`.
    """
    mermaid = "graph TD\n  A[Motor de reglas] --> B[Backend FastAPI]\n"
    propuesta = "## Componentes\n- **Motor de reglas (Drools)**: decisiones.\n"
    plan = build_plan(
        provider_id="aws", mermaid=mermaid, proposal_markdown=propuesta
    )
    assert plan.unmapped == ("Motor de reglas (Drools)",)


def test_no_junta_componentes_que_solo_se_parecen():
    mermaid = "graph TD\n  A[Motor de reglas] --> B[Firma digital]\n"
    plan = build_plan(provider_id="aws", mermaid=mermaid)
    assert len(plan.unmapped) == 2


def test_un_componente_desconocido_se_reporta_en_vez_de_inventarse():
    """Preferimos decir "esto no lo sé mapear" a poner un servicio al azar."""
    plan = build_plan(
        provider_id="aws", mermaid="graph TD\n  X[Cosa rarisima inclasificable]\n"
    )
    assert plan.components == ()
    assert plan.unmapped == ("Cosa rarisima inclasificable",)


@pytest.mark.parametrize("provider_id", ["aws", "gcp"])
@pytest.mark.parametrize(
    "componente",
    ["Dominio", "Dominio (Modelos y reglas)", "Capa de Dominio"],
)
def test_la_capa_de_dominio_no_es_un_servicio_de_dns(provider_id, componente):
    """En estas arquitecturas "dominio" es la capa de negocio, no un nombre
    DNS. Con "dominio" como término del catálogo, "Dominio (Modelos y
    reglas)" salía mapeado a Route 53, que es un error visible en la tabla.
    Preferimos dejarlo sin mapear antes que mapearlo mal."""
    plan = build_plan(provider_id=provider_id, mermaid=f"graph TD\n  A[{componente}]\n")
    categorias = {m.service.category for m in plan.components}
    assert "dns" not in categorias


@pytest.mark.parametrize("provider_id", ["aws", "gcp"])
@pytest.mark.parametrize("componente", ["Nombre de dominio", "DNS", "Dominio web"])
def test_el_dns_de_verdad_si_se_mapea(provider_id, componente):
    plan = build_plan(provider_id=provider_id, mermaid=f"graph TD\n  A[{componente}]\n")
    assert [m.service.category for m in plan.components] == ["dns"]


def test_el_termino_mas_especifico_gana():
    """"base de datos" tiene que pesar más que "bd" o "sql" sueltos."""
    plan = build_plan(provider_id="aws", mermaid="graph TD\n  A[Base de datos]\n")
    assert plan.components[0].service.id == "rds"
    assert plan.components[0].reason == "base de datos"


def test_dos_componentes_pueden_caer_en_el_mismo_servicio():
    plan = build_plan(
        provider_id="gcp",
        mermaid="graph TD\n  A[Cola de mensajes] --> B[Notificaciones]\n",
    )
    assert {m.service.id for m in plan.components} == {"pubsub"}
    # Pero el diagrama dibuja UNA caja, con los dos componentes dentro.
    assert len(plan.services) == 1
    assert len(plan.components_for("pubsub")) == 2


# --------------------------------------------------------------------------
# Conexiones
# --------------------------------------------------------------------------


def test_las_conexiones_salen_de_la_arquitectura_aprobada():
    plan = build_plan(provider_id="aws", mermaid=MERMAID)
    assert ("ecs", "rds") in plan.connections
    assert ("ecs", "elasticache") in plan.connections


def test_no_dibuja_conexiones_que_el_proveedor_no_permite():
    """Todo par dibujado tiene que estar declarado en `connects_to`."""
    for provider_id in ("aws", "gcp"):
        plan = build_plan(
            provider_id=provider_id, mermaid=MERMAID, proposal_markdown=PROPUESTA
        )
        permitidas = {
            (s.id, destino)
            for s in plan.provider.services
            for destino in s.connects_to
        }
        for par in plan.connections:
            assert par in permitidas, f"{provider_id}: {par} no está en connects_to"


def test_inserta_el_servicio_intermedio_cuando_hace_falta():
    """CloudFront no habla con ECS: habla con el balanceador o el gateway.
    En vez de descartar la flecha del frontend al backend, se mete el
    intermediario que el catálogo sí permite."""
    plan = build_plan(
        provider_id="aws",
        mermaid="graph TD\n  FE[Frontend React] --> API[Backend FastAPI]\n",
    )
    assert plan.bridges, "esperaba un servicio puente entre la CDN y el cómputo"
    puente = plan.bridges[0].id
    assert ("cloudfront", puente) in plan.connections
    assert (puente, "ecs") in plan.connections
    # El puente no corresponde a ningún componente de la arquitectura.
    assert plan.components_for(puente) == []


def test_endereza_una_flecha_dibujada_al_reves():
    """Si la arquitectura dibuja "base de datos -> backend", en la nube el
    que llama es el backend."""
    plan = build_plan(
        provider_id="aws",
        mermaid="graph TD\n  DB[(Base de datos PostgreSQL)] --> API[Backend FastAPI]\n",
    )
    assert ("ecs", "rds") in plan.connections
    assert ("rds", "ecs") not in plan.connections


def test_sin_flechas_usa_las_conexiones_del_catalogo():
    """Un diagrama de cajas sueltas no debe dar un despliegue sin ninguna
    línea: se completan las conexiones posibles entre los servicios."""
    plan = build_plan(
        provider_id="aws",
        mermaid="graph TD\n  A[Backend FastAPI]\n  B[(Base de datos PostgreSQL)]\n",
    )
    assert ("ecs", "rds") in plan.connections


# --------------------------------------------------------------------------
# Serialización
# --------------------------------------------------------------------------


def test_plan_to_dict_trae_lo_que_consume_la_interfaz():
    plan = build_plan(provider_id="aws", mermaid=MERMAID, proposal_markdown=PROPUESTA)
    data = plan_to_dict(plan)
    assert data["provider"]["id"] == "aws"
    assert {"component", "service_id", "service_name", "deploy_note"} <= set(
        data["components"][0]
    )
    # La nota de despliegue es lo que responde "dónde va cada pieza".
    assert all(item["deploy_note"] for item in data["components"])
