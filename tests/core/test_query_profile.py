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
