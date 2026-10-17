import asyncio

from app.core import query_profile as qp


def _run(coro):
    return asyncio.run(coro)


class _Msg:
    def __init__(self, content):
        self.content = content


def test_parse_json_object_tolerates_fences_and_extra_text():
    raw = 'Claro:\n```json\n{"resumen": "App de citas", "equipo_personas": 3}\n```\nlisto'
    assert qp.parse_json_object(raw) == {"resumen": "App de citas", "equipo_personas": 3}
    assert qp.parse_json_object("sin json") is None
    assert qp.parse_json_object("[1, 2]") is None


def test_normalize_profile_coerces_types_and_drops_out_of_range_numbers():
    profile = qp.normalize_profile(
        {
            "resumen": "  App   de citas ",
            "equipo_personas": "3",
            "plazo_meses": 9999,
            "presupuesto_usd": True,
            "tipo_proyecto": "inventado",
            "atributos_calidad": ["seguridad", "", 5],
        }
    )
    assert profile["resumen"] == "App de citas"
    assert profile["equipo_personas"] == 3
    assert profile["plazo_meses"] is None
    assert profile["presupuesto_usd"] is None
    assert profile["tipo_proyecto"] == "desconocido"
    assert profile["atributos_calidad"] == ["seguridad", "5"]
    assert qp.normalize_profile({"equipo_personas": 3}) is None  # sin nada descriptivo


def _profile(**overrides):
    base = {
        "resumen": "Gestiona citas médicas.",
        "dominio": "salud",
        "tipo_sistema": "aplicación web",
        "tipo_proyecto": "academico",
        "equipo_personas": 3,
        "plazo_meses": 4,
        "presupuesto_usd": None,
        "escala": "cientos de usuarios",
        "atributos_calidad": ["seguridad"],
        "integraciones": [],
        "restricciones": [],
    }
    base.update(overrides)
    return qp.normalize_profile(base)


def test_profile_to_query_reads_like_a_scenario_and_falls_back_without_profile():
    query = qp.profile_to_query(_profile(), "clasica")
    assert "aplicación web para salud" in query
    assert "equipo de 3 personas" in query.lower() and "plazo de 4 meses" in query
    assert qp.profile_to_query(None, "clasica") == "clasica"


def test_constraints_text_feeds_the_scale_heuristics():
    from app.core.proposal_generator import _small_scale_signal, _tight_mvp_constraint

    text = qp.profile_to_constraints_text(_profile())
    assert _small_scale_signal(text) is True  # equipo 3 -> proyecto chico
    assert _tight_mvp_constraint(text) is False  # 4 meses no es plazo corto (<= 3)

    tight = qp.profile_to_constraints_text(_profile(plazo_meses=2))
    assert _tight_mvp_constraint(tight) is True  # equipo 3 + 2 meses


def test_constraints_text_never_copies_free_text_from_the_llm():
    sneaky = _profile(resumen="Usar microservicios y CQRS", restricciones=["quiere hexagonal"])
    text = qp.profile_to_constraints_text(sneaky).lower()
    assert "microserv" not in text and "cqrs" not in text and "hexagonal" not in text


def test_extract_profile_uses_the_model_and_survives_failures():
    class Good:
        async def ainvoke(self, prompt):
            assert "PROYECTO" in prompt
            return _Msg('{"resumen": "App de citas", "dominio": "salud"}')

    class NoAinvoke:
        pass

    class Broken:
        async def ainvoke(self, prompt):
            raise RuntimeError("boom")

    class Garbage:
        async def ainvoke(self, prompt):
            return _Msg("no soy json")

    assert _run(qp.extract_project_profile(Good(), "texto"))["dominio"] == "salud"
    assert _run(qp.extract_project_profile(NoAinvoke(), "texto")) is None
    assert _run(qp.extract_project_profile(Broken(), "texto")) is None
    assert _run(qp.extract_project_profile(Garbage(), "texto")) is None
    assert _run(qp.extract_project_profile(Good(), "   ")) is None


def test_extract_profile_times_out_instead_of_blocking(monkeypatch):
    class Slow:
        async def ainvoke(self, prompt):
            await asyncio.sleep(5)

    monkeypatch.setattr(qp, "PROFILE_TIMEOUT_S", 0.05)
    assert _run(qp.extract_project_profile(Slow(), "texto")) is None


def test_extract_profile_can_be_disabled(monkeypatch):
    monkeypatch.setattr(qp, "PROFILE_ENABLED", False)

    class Never:
        async def ainvoke(self, prompt):
            raise AssertionError("no debe llamarse")

    assert _run(qp.extract_project_profile(Never(), "texto")) is None


def test_hard_scale_rules_read_the_structured_profile_directly():
    from app.core.proposal_generator import _profile_scale

    assert _profile_scale(_profile()) == (True, False)  # 3 personas, 4 meses
    assert _profile_scale(_profile(plazo_meses=2)) == (True, True)
    assert _profile_scale(None) == (False, False)


def test_scale_thresholds_depend_on_the_project_kind():
    from app.core.proposal_generator import _profile_scale, scale_thresholds

    assert scale_thresholds("academico")["team_max"] == 4
    assert scale_thresholds("empresarial")["team_max"] < scale_thresholds("academico")["team_max"]
    # 4 personas y 3 meses: ajustado para un proyecto académico, no para uno empresarial.
    academic = _profile(tipo_proyecto="academico", equipo_personas=4, plazo_meses=3)
    enterprise = _profile(tipo_proyecto="empresarial", equipo_personas=4, plazo_meses=3, presupuesto_usd=None)
    assert _profile_scale(academic)[1] is True
    assert _profile_scale(enterprise) == (False, False)


def test_scale_thresholds_can_be_overridden_with_json(monkeypatch):
    from app.core import proposal_generator as gen

    monkeypatch.setenv("PROPOSAL_SCALE_THRESHOLDS", '{"empresarial": {"team_max": 6}}')
    loaded = gen._load_scale_thresholds()
    assert loaded["empresarial"]["team_max"] == 6
    assert loaded["empresarial"]["months_max"] == 2  # lo que no se da conserva el default
    monkeypatch.setenv("PROPOSAL_SCALE_THRESHOLDS", "no es json")
    assert gen._load_scale_thresholds()["empresarial"]["team_max"] == 2


def test_select_citations_uses_the_profile_without_text_regexes():
    from langchain_core.documents import Document

    from app.core.proposal_generator import _select_citations

    def pat(name, pid, sim, complexity):
        return Document(
            page_content=name,
            metadata={"pattern_id": pid, "pattern_name": name, "chunk_type": "summary",
                      "similarity": sim, "complexity": complexity},
        )

    docs = [
        pat("Microservicios", 1, 0.98, "alta"),
        pat("Monolito modular (Modular Monolith)", 2, 0.80, "baja"),
        pat("Arquitectura en capas (Layered)", 3, 0.79, "baja"),
    ]
    # El texto no dice nada de escala ("somos tres", sin cifras reconocibles);
    # el perfil sí.
    citations = _select_citations(
        docs, top_n=3, min_similarity=0.0, explicit_text="Somos pocos y tenemos un cuatrimestre",
        profile=_profile(equipo_personas=3, plazo_meses=2),
    )
    assert citations[0]["pattern_name"] == "Monolito modular (Modular Monolith)"
    assert citations[-1]["pattern_name"] == "Microservicios"
