"""
Pruebas de la página HTML del diagrama de despliegue.

El render final lo hace Puppeteer (no se prueba acá: necesita el sidecar).
Lo que sí se puede fijar es que la página traiga todo lo necesario para
dibujarse: los logos embebidos, un nodo por servicio con el id que esperan
las flechas, y las conexiones del plan.
"""

import re

from app.core import deployment_diagram
from app.core.deployment_diagram import build_deployment_html, stash_page, take_page
from app.core.deployment_mapper import build_plan

MERMAID = """graph TD
    FE[Frontend React SPA] --> API[Backend API FastAPI]
    API --> DB[(Base de datos PostgreSQL)]
    API --> COLA[Cola de mensajes]
"""


def _html(provider_id: str = "aws") -> str:
    plan = build_plan(provider_id=provider_id, mermaid=MERMAID)
    return build_deployment_html(plan, project_name="Proyecto de prueba")


def test_la_pagina_es_autocontenida():
    """El sidecar de Puppeteer no tiene salida a internet ni acceso al disco
    del backend: cualquier `src` externo daría un ícono roto."""
    html = _html()
    assert "data:image/png;base64," in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")


def test_incluye_un_nodo_por_servicio_con_el_id_que_usan_las_flechas():
    plan = build_plan(provider_id="aws", mermaid=MERMAID)
    html = build_deployment_html(plan)
    for service in plan.services:
        assert f"id='svc-{service.id}'" in html


def test_las_conexiones_viajan_a_la_pagina():
    plan = build_plan(provider_id="aws", mermaid=MERMAID)
    html = build_deployment_html(plan)
    for origen, destino in plan.connections:
        assert f'"from": "{origen}", "to": "{destino}"' in html


def test_muestra_el_nombre_del_proveedor_y_del_proyecto():
    html = _html("gcp")
    assert "Google Cloud Platform" in html
    assert "Proyecto de prueba" in html


def test_nombra_los_componentes_que_aloja_cada_servicio():
    html = _html()
    assert "Backend API FastAPI" in html
    assert "Base de datos PostgreSQL" in html


def test_marca_los_servicios_puente_como_agregados_por_el_proveedor():
    plan = build_plan(
        provider_id="aws",
        mermaid="graph TD\n  FE[Frontend React] --> API[Backend FastAPI]\n",
    )
    html = build_deployment_html(plan)
    assert plan.bridges
    assert "Lo agrega el proveedor" in html


def test_avisa_de_los_componentes_sin_equivalente():
    plan = build_plan(
        provider_id="aws",
        mermaid="graph TD\n  A[Backend FastAPI] --> B[Cosa rarisima inclasificable]\n",
    )
    html = build_deployment_html(plan)
    assert "Sin equivalente directo" in html
    assert "Cosa rarisima inclasificable" in html


def test_escapa_el_texto_del_usuario():
    """El nombre del proyecto lo escribe el usuario y entra en el HTML."""
    plan = build_plan(provider_id="aws", mermaid=MERMAID)
    html = build_deployment_html(plan, project_name="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_pone_el_titulo_de_listo_al_terminar():
    """El backend espera a `deployment-rendered` antes de capturar; sin esa
    línea la captura saldría antes de que se tracen las flechas."""
    html = _html()
    assert "deployment-rendered" in html
    assert "document.title" in html


class TestEntregaDeLaPagina:
    """La página se sirve por HTTP, no se manda como `data:` URL.

    Lleva los logos embebidos y pesa más de 100 KB; el transporte del sidecar
    de Puppeteer rechaza una petición de ese tamaño (413), que es lo que hacía
    fallar el render con "unhandled errors in a TaskGroup".
    """

    def test_guarda_y_devuelve_la_pagina(self):
        token = stash_page("<html>hola</html>")
        assert take_page(token) == "<html>hola</html>"

    def test_un_token_desconocido_no_devuelve_nada(self):
        assert take_page("no-existe") is None

    def test_la_pagina_caduca(self, monkeypatch):
        """No se quedan páginas en memoria si un render se cuelga."""
        monkeypatch.setattr(deployment_diagram, "_PAGE_TTL_SECONDS", 0.0)
        token = stash_page("<html>x</html>")
        assert take_page(token) is None

    def test_dos_renders_no_se_pisan(self):
        uno, dos = stash_page("<html>1</html>"), stash_page("<html>2</html>")
        assert uno != dos
        assert take_page(uno) == "<html>1</html>"
        assert take_page(dos) == "<html>2</html>"

    def test_el_backend_se_nombra_por_su_servicio_de_docker(self):
        """Quien pide la página es el navegador del sidecar, no el usuario:
        `localhost` ahí sería el propio sidecar."""
        assert "localhost" not in deployment_diagram.RENDER_BASE_URL
        assert deployment_diagram.RENDER_BASE_URL.startswith("http")


def test_el_svg_de_las_flechas_queda_debajo_de_las_tarjetas():
    """Si el SVG quedara encima, las flechas taparían los logos."""
    html = _html()
    svg_rule = re.search(r"svg#wires\s*\{[^}]*\}", html)
    assert svg_rule and "z-index: 0" in svg_rule.group(0)
