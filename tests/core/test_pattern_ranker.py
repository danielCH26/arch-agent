import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.documents import Document

from app.core import pattern_ranker as pr

LAYERED = "Arquitectura en capas (Layered)"
MODULAR = "Monolito modular (Modular Monolith)"
MICRO = "Microservicios"


def _doc(name, pid, similarity, complexity="baja", chunk_type="summary"):
    return Document(
        page_content=f"{name} [{chunk_type}]",
        metadata={
            "pattern_id": pid,
            "pattern_name": name,
            "chunk_type": chunk_type,
            "similarity": similarity,
            "complexity": complexity,
            "tradeoffs": {"ventajas": ["a"], "desventajas": ["b"]},
        },
    )


DOCS = [
    _doc(MICRO, 1, 0.90, "alta"),
    _doc(LAYERED, 2, 0.86, "baja"),
    _doc(MODULAR, 3, 0.84, "baja"),
]


def test_parse_ranking_validates_against_real_names():
    names = [MICRO, MODULAR, LAYERED]
    raw = '{"ranking": ["monolito modular (modular monolith)", "Inventado", "Monolito modular (Modular Monolith)"], "razones": {"Monolito modular (Modular Monolith)": "encaja", "X": "no"}}'
    ranking, reasons = pr.parse_ranking(raw, names)
    assert ranking == [MODULAR, MICRO, LAYERED]  # omitidos al final, en su orden
    assert reasons == {MODULAR: "encaja"}
    assert pr.parse_ranking("nada", names) is None
    assert pr.parse_ranking('{"ranking": ["Inventado"]}', names) is None


def test_rank_candidates_skips_when_there_is_nothing_to_choose():
    class Never:
        async def ainvoke(self, prompt):
            raise AssertionError

    cands = [{"pattern_name": MICRO}]
    assert asyncio.run(pr.rank_candidates(Never(), "proyecto", cands)) is None
    assert asyncio.run(pr.rank_candidates(Never(), "", cands * 2)) is None


def test_rank_candidates_returns_none_when_the_model_fails():
    class Broken:
        async def ainvoke(self, prompt):
            raise RuntimeError("boom")

    cands = [{"pattern_name": MICRO}, {"pattern_name": LAYERED}]
    assert asyncio.run(pr.rank_candidates(Broken(), "proyecto", cands)) is None


def test_llm_ranking_breaks_ties_between_eligible_patterns():
    from app.core.proposal_generator import _select_citations

    without = _select_citations(DOCS, top_n=3, min_similarity=0.0)
    with_llm = _select_citations(
        DOCS,
        top_n=3,
        min_similarity=0.0,
        llm_ranking=[MODULAR, LAYERED, MICRO],
        llm_reasons={MODULAR: "límites claros por dominio"},
    )
    assert without[0]["pattern_name"] != MODULAR
    assert with_llm[0]["pattern_name"] == MODULAR
    assert with_llm[0]["llm_reason"] == "límites claros por dominio"
    assert "llm_reason" not in with_llm[1]


def test_llm_ranking_cannot_override_the_hard_scale_rule():
    from app.core.proposal_generator import _select_citations

    text = "Equipo de 3 personas, plazo de 2 meses."
    citations = _select_citations(
        DOCS,
        top_n=3,
        min_similarity=0.0,
        explicit_text=text,
        llm_ranking=[MICRO, MODULAR, LAYERED],
    )
    assert citations[0]["pattern_name"] != MICRO
    assert citations[-1]["pattern_name"] == MICRO


def test_llm_ranking_cannot_override_what_the_user_asked_for_or_rejected():
    from app.core.proposal_generator import _select_citations

    wanted = _select_citations(
        DOCS, top_n=3, min_similarity=0.0, feedback="cambia a monolito modular", llm_ranking=[LAYERED, MICRO, MODULAR]
    )
    assert wanted[0]["pattern_name"] == MODULAR
    rejected = _select_citations(
        DOCS, top_n=3, min_similarity=0.0, feedback="sin microservicios", llm_ranking=[MICRO, LAYERED, MODULAR]
    )
    assert MICRO not in [c["pattern_name"] for c in rejected]


# --- integracion con generate_stream ------------------------------------------------


class _Msg:
    def __init__(self, content):
        self.content = content
        self.response_metadata = {}


def _stream(requirements, ranking_json, model_has_ainvoke=True):
    from app.core import proposal_generator as gen

    queries = []

    class _Model:
        async def astream(self, _prompt):
            yield _Msg("## Componentes\n")

        async def ainvoke(self, prompt):
            if "analista de requerimientos" in prompt:
                return _Msg('{"resumen": "Gestor de citas", "dominio": "salud", "tipo_sistema": "aplicación web", "equipo_personas": 3, "plazo_meses": 4}')
            return _Msg(ranking_json)

    model = _Model()
    if not model_has_ainvoke:
        del _Model.ainvoke

    def _retrieve(query, _user_id):
        queries.append(query)
        return DOCS

    project = SimpleNamespace(name="Citas", description="d")
    with patch.object(gen, "_load_project_and_session", return_value=(project, 1)), \
        patch.object(gen, "load_requirements_text", return_value=requirements), \
        patch.object(gen, "load_documents_text", return_value=("", [])), \
        patch.object(gen, "_retrieve_patterns", side_effect=_retrieve), \
        patch.object(gen, "build_langchain_model", return_value=model), \
        patch.object(gen, "_missing_sections", return_value=[]), \
        patch.object(gen, "_persist_proposal_and_log", side_effect=lambda **kw: (7, 8, 1)), \
        patch.object(gen, "_engram_mirror", new=_noop):
        async def _run():
            return [e async for e in gen.ProposalGenerator(user_id=1, project_id=1).generate_stream()]

        events = asyncio.run(_run())
    return events, queries


async def _noop(**_kwargs):
    return None


def test_generate_stream_queries_with_the_profile_and_uses_the_llm_ranking():
    ranking = f'{{"ranking": ["{MODULAR}", "{LAYERED}", "{MICRO}"], "razones": {{"{MODULAR}": "módulos claros"}}}}'
    events, queries = _stream("Somos un equipo pequeño.", ranking)
    assert "aplicación web para salud" in queries[0]
    sources = next(payload for name, payload in events if name == "sources")
    assert sources[0]["pattern_name"] == MODULAR
    assert sources[0]["llm_reason"] == "módulos claros"


def test_generate_stream_falls_back_to_classic_query_and_similarity_order_without_ainvoke():
    events, queries = _stream("Somos un equipo pequeño.", "{}", model_has_ainvoke=False)
    assert queries[0].startswith("Citas")  # consulta clasica: nombre del proyecto primero
    sources = next(payload for name, payload in events if name == "sources")
    assert sources[0]["pattern_name"] == LAYERED  # similitud menos penalizacion por complejidad


def test_generate_stream_profile_numbers_trigger_the_scale_rule_even_if_the_text_does_not():
    ranking = f'{{"ranking": ["{MICRO}", "{LAYERED}", "{MODULAR}"]}}'
    events, _ = _stream("Queremos una app de citas médicas.", ranking)  # el texto no dice equipo ni plazo
    sources = next(payload for name, payload in events if name == "sources")
    assert sources[0]["pattern_name"] != MICRO  # equipo 3 + plazo 4 meses salieron del perfil
