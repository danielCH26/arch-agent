"""Plantillas de diagrama por patron principal (app/core/diagram_templates.py)."""

from pathlib import Path

import yaml

from app.core.diagram_templates import (
    DIAGRAM_TEMPLATES,
    render_template_hint,
    select_diagram_template,
    template_for_pattern_name,
    template_for_proposal,
)

PATTERNS_DIR = Path(__file__).resolve().parents[2] / "data" / "patterns"

EXPECTED_KEY_BY_FILE = {
    "api_gateway_bff.yaml": "api_gateway_bff",
    "clean_architecture.yaml": "clean",
    "cqrs.yaml": "cqrs",
    "etl_pipeline.yaml": "etl",
    "event_driven.yaml": "event_driven",
    "event_sourcing.yaml": "event_sourcing",
    "hexagonal.yaml": "hexagonal",
    "lambda_kappa.yaml": "lambda_kappa",
    "layered.yaml": "layered",
    "medallion_lakehouse.yaml": "medallion",
    "microkernel.yaml": "microkernel",
    "microservices.yaml": "microservices",
    "mlops_pipeline.yaml": "mlops",
    "modular_monolith.yaml": "modular_monolith",
    "mvc_mvvm.yaml": "mvc_mvvm",
    "pipes_filters.yaml": "pipes_filters",
    "saga.yaml": "saga",
    "serverless.yaml": "serverless",
    "soa.yaml": "soa",
}


def _approved(text: str) -> dict:
    return {
        "page_content": f"PROPUESTA APROBADA PARA USAR COMO FUENTE DE VERDAD EN EL DIAGRAMA:\n{text}",
        "metadata": {"source_type": "approved_proposal"},
    }


def test_every_catalog_pattern_has_its_own_template():
    files = sorted(path.name for path in PATTERNS_DIR.glob("*.yaml"))
    assert set(files) == set(EXPECTED_KEY_BY_FILE)
    for filename in files:
        pattern = yaml.safe_load((PATTERNS_DIR / filename).read_text(encoding="utf-8"))
        template = template_for_pattern_name(pattern["pattern_name"])
        assert template is not None, filename
        assert template.key == EXPECTED_KEY_BY_FILE[filename], (filename, template.key)


def test_template_keys_are_unique():
    keys = [template.key for template in DIAGRAM_TEMPLATES]
    assert len(keys) == len(set(keys))


def test_no_template_forces_observability_gateway_or_deployment():
    for template in DIAGRAM_TEMPLATES:
        text = template.skeleton.casefold()
        assert "observabilidad" not in text, template.key
        assert "kubernetes" not in text, template.key
        for deployment_node in ("docker", "contenedor", "ci/cd", "load balancer"):
            assert deployment_node not in text, (template.key, deployment_node)
        if "api gateway" in text:
            assert "solo si" in text, template.key


def test_principal_line_in_patterns_section_wins():
    proposal = (
        "## Componentes\n- API REST\n\n"
        "## Patrones\n"
        "- Secundario: CQRS en su version minima\n"
        "- Patron principal: Arquitectura hexagonal\n\n"
        "## Justificación del patrón principal\n- Motivo: microservicios descartados\n"
    )
    assert template_for_proposal(proposal).key == "hexagonal"


def test_first_mention_in_patterns_section_when_no_principal_line():
    proposal = (
        "## Componentes\n- Broker de eventos (descartado)\n\n"
        "## Patrones\n- Monolito modular\n- Event sourcing para pagos\n"
    )
    assert template_for_proposal(proposal).key == "modular_monolith"


def test_longest_keyword_wins_at_same_position():
    assert template_for_proposal("## Patrones\n- Event sourcing\n").key == "event_sourcing"
    assert template_for_proposal("## Patrones\n- Lambda / Kappa\n").key == "lambda_kappa"


def test_select_only_uses_the_approved_proposal():
    rag_pattern = {
        "page_content": "Microservicios ...",
        "metadata": {"source_type": "architect_pattern", "pattern_name": "Microservicios"},
    }
    assert select_diagram_template([rag_pattern]) is None
    selected = select_diagram_template(
        [_approved("## Patrones\n- Principal: Arquitectura en capas\n"), rag_pattern]
    )
    assert selected.key == "layered"


def test_render_hint_mentions_label_and_grounding_rule():
    hint = render_template_hint(template_for_pattern_name("Pipeline de MLOps"))
    assert "Pipeline de MLOps" in hint
    assert "Usa solo los componentes que nombra la propuesta" in hint
    assert render_template_hint(None) == ""
