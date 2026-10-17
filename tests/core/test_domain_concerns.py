"""Preocupaciones transversales del dominio (ubicación, archivos, pagos...)."""

from app.core.domain_concerns import (
    DOMAIN_CONCERNS,
    concern_by_question,
    relevant_concerns,
    uncovered_concerns,
)
from app.core.elicitation_agent import _es_pregunta_compuesta


def _keys(concerns):
    return [c.key for c in concerns]


def test_lost_pets_needs_maps_files_and_notifications():
    keys = _keys(relevant_concerns("App para reportar mascotas perdidas en el barrio"))
    assert {"ubicacion", "archivos", "notificaciones", "respaldos"} <= set(keys)


def test_a_health_domain_brings_personal_data_even_without_keywords():
    assert "datos_personales" in _keys(relevant_concerns("Agenda de turnos", domain="Salud"))
    assert "datos_personales" in _keys(relevant_concerns("Una clínica de salud"))


def test_mentioning_the_concern_covers_it():
    text = "Mascotas perdidas, con un mapa de avistamientos"
    uncovered = _keys(uncovered_concerns(text, text))
    assert "ubicacion" not in uncovered
    assert "archivos" in uncovered


def test_backups_always_apply_but_can_be_left_out_of_the_interview():
    assert "respaldos" in _keys(uncovered_concerns("Un CRUD", "Un CRUD"))
    assert "respaldos" not in _keys(uncovered_concerns("Un CRUD", "Un CRUD", include_always=False))


def test_keywords_need_word_boundaries():
    # "mapache" no es "mapa"; "cobrar" no cubre "cobros".
    assert "ubicacion" not in _keys(relevant_concerns("Refugio de mapaches"))


def test_every_concern_has_one_granular_question_and_an_open_question():
    for concern in DOMAIN_CONCERNS:
        assert concern.question.startswith("¿") and concern.question.endswith("?"), concern.key
        assert not _es_pregunta_compuesta(concern.question), concern.key
        assert concern.open_question, concern.key
        assert concern_by_question(concern.question) is concern
