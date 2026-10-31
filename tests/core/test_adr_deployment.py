"""
El despliegue en la nube dentro del ADR.

El ADR documenta decisiones, así que solo entra el despliegue APROBADO: uno
generado y sin decidir todavía es un borrador.
"""

from app.core.adr_generator import (
    AdrContext,
    _deployment_block,
    deployment_matches_architecture,
)


def _ctx(deployment=None) -> AdrContext:
    return AdrContext(
        project_name="Proyecto de prueba",
        project_description="",
        current_phase="revision",
        deployment=deployment,
    )

PLAN = {
    "provider": {"id": "aws", "name": "Amazon Web Services", "short_name": "AWS"},
    "components": [
        {
            "component": "Backend API FastAPI",
            "service_name": "Amazon ECS",
            "deploy_note": "Sube la imagen a ECR y despliégala como servicio de ECS.",
        },
        {
            "component": "Base de datos PostgreSQL",
            "service_name": "Amazon RDS (PostgreSQL)",
            "deploy_note": "Crea la instancia en subredes privadas.",
        },
    ],
    "bridges": [{"service_name": "Amazon API Gateway"}],
    "unmapped": [],
}


def test_sin_despliegue_aprobado_no_agrega_nada():
    """El ADR de un proyecto que no llegó a aprobar un despliegue queda
    exactamente como antes de esta funcionalidad."""
    assert _deployment_block(_ctx()) == ""


def test_un_plan_vacio_tampoco_agrega_la_seccion():
    ctx = _ctx({"provider": {}, "components": []})
    assert _deployment_block(ctx) == ""


def test_escribe_la_tabla_de_donde_va_cada_pieza():
    bloque = _deployment_block(_ctx(PLAN))
    assert "### Despliegue en Amazon Web Services" in bloque
    assert "| Componente | Servicio | Cómo se despliega |" in bloque
    assert "Backend API FastAPI" in bloque
    assert "Amazon RDS (PostgreSQL)" in bloque
    # La instrucción concreta es lo que hace útil la tabla.
    assert "Sube la imagen a ECR" in bloque


def test_distingue_los_servicios_que_pone_el_proveedor():
    """Un servicio puente no sale de un componente de la arquitectura; el
    ADR tiene que decirlo o parecería que falta justificarlo."""
    bloque = _deployment_block(_ctx(PLAN))
    assert "Amazon API Gateway" in bloque
    assert "no salen de un componente" in bloque


def test_deja_constancia_de_lo_que_quedo_sin_mapear():
    plan = {**PLAN, "unmapped": ["Servicio de firma digital"]}
    bloque = _deployment_block(_ctx(plan))
    assert "Servicio de firma digital" in bloque
    assert "pendientes de decidir" in bloque


def test_es_una_subseccion_y_no_renumera_el_adr():
    """Va como `###` dentro de "4. Diagrama de arquitectura". Si fuera una
    sección numerada nueva habría que renumerar 5, 6 y 7, y hay código que
    las busca por número (la guía es "## 7.", los saltos de página del PDF,
    el lint de la guía)."""
    bloque = _deployment_block(_ctx(PLAN))
    assert bloque.lstrip().startswith("###")
    assert "## 5." not in bloque


class TestNoMezclaArquitecturas:
    """Si después de aprobar un despliegue se aprueba OTRO diagrama de
    arquitectura, el de antes ya no describe lo que hay. Sin este filtro el
    ADR enseñaba el diagrama nuevo junto a la tabla vieja."""

    def test_acepta_el_despliegue_de_esta_arquitectura(self):
        att = {"architecture_attachment_id": "arq-1"}
        assert deployment_matches_architecture(att, "arq-1") is True

    def test_descarta_el_calculado_sobre_otra(self):
        att = {"architecture_attachment_id": "arq-1"}
        assert deployment_matches_architecture(att, "arq-2") is False

    def test_acepta_los_guardados_antes_de_registrar_ese_dato(self):
        """Descartarlos dejaría sin despliegue a los ADR ya generados."""
        assert deployment_matches_architecture({}, "arq-1") is True

    def test_sin_arquitectura_de_referencia_no_filtra(self):
        att = {"architecture_attachment_id": "arq-1"}
        assert deployment_matches_architecture(att, None) is True
