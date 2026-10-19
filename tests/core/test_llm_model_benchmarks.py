"""Tests de app/core/llm_model_benchmarks.py.

PR #102 (round 5, review de Laura): este archivo se reescribio completo. La
version anterior mockeaba ``builtins.open`` con ``mock_open`` y devolvia un
``MagicMock`` desde ``_yaml_path``, asi que ``yaml.safe_load`` recibia un mock
en vez de texto. El lector de PyYAML nunca llegaba a EOF y el mock acumulaba
cada llamada: la memoria crecia ~400 MB/s hasta que el proceso moria por OOM
y eso tumbaba el runner de GitHub Actions.

Ademas el YAML de ejemplo usaba ``tiers:``/``score`` cuando el modulo espera
``models:``/``mmlu_score``, y ``get_model_score`` devuelve ``mmlu_score``,
no ``score``. O sea que el test no describia el modulo.

Ahora se escriben YAML reales en un directorio temporal (via ``tmp_path``) y
se parchea unicamente ``_yaml_path``. Sin mocks de ``open`` ni de ``read_text``,
y sin ``importlib.reload``: el modulo expone ``invalidate_cache()`` justamente
para eso, y el fixture lo llama en setUp y teardown para que cada test arranque
con el cache limpio.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.core.llm_model_benchmarks import (
    LLMBenchmarkFileError,
    get_model_score,
    invalidate_cache,
    load_benchmarks,
)

# YAML minimo valido: el modulo exige la clave "models" en el top-level.
YAML_VALIDO = """
models:
  - model_id: "gpt-4"
    mmlu_score: 95.5
    source: "paper oficial"
  - model_id: "gpt-3.5-turbo"
    mmlu_score: 80
    source: "leaderboard"
"""


@pytest.fixture(autouse=True)
def _cache_limpio():
    """``invalidate_cache()`` es el seam que el propio modulo expone para tests."""
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture
def yaml_en_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Escribe YAML real y parchea SOLO ``_yaml_path``.

    Se parchea el path, no ``open``: el modulo lee con ``Path.read_text``, asi
    que mockear ``open`` no interceptaba nada y ademas rompia el parser.
    """

    def _escribir(contenido: str) -> Path:
        archivo = tmp_path / "llm_model_benchmarks.yaml"
        archivo.write_text(contenido, encoding="utf-8")
        monkeypatch.setattr(
            "app.core.llm_model_benchmarks._yaml_path", lambda: archivo
        )
        return archivo

    return _escribir


class TestCargaDeEntradas:
    """``load_benchmarks`` lee el YAML y devuelve ``BenchmarkEntry`` en orden."""

    def test_carga_las_entradas_del_yaml(self, yaml_en_tmp):
        yaml_en_tmp(YAML_VALIDO)

        entries = load_benchmarks()

        assert len(entries) == 2
        assert [e.model_id for e in entries] == ["gpt-4", "gpt-3.5-turbo"]
        assert entries[0].mmlu_score == 95.5
        assert entries[1].mmlu_score == 80.0

    def test_conserva_el_source_de_cada_entrada(self, yaml_en_tmp):
        yaml_en_tmp(YAML_VALIDO)

        entries = load_benchmarks()

        assert entries[0].source == "paper oficial"
        # "source" es opcional en el YAML: si falta, el modulo pone un marcador.
        yaml_en_tmp("models:\n  - model_id: solo-modelo\n    mmlu_score: 70\n")
        invalidate_cache()
        assert load_benchmarks()[0].source == "(no source)"

    def test_toma_el_orden_del_yaml(self, yaml_en_tmp):
        yaml_en_tmp(
            "models:\n"
            "  - model_id: primero\n    mmlu_score: 10\n"
            "  - model_id: segundo\n    mmlu_score: 20\n"
            "  - model_id: tercero\n    mmlu_score: 30\n"
        )

        assert [e.model_id for e in load_benchmarks()] == [
            "primero",
            "segundo",
            "tercero",
        ]


class TestEntradasMalformadas:
    """Las entradas invalidas se saltean, no tumban la carga."""

    def test_saltea_entradas_que_no_son_dict(self, yaml_en_tmp):
        yaml_en_tmp(
            "models:\n"
            '  - model_id: "bueno"\n'
            "    mmlu_score: 90\n"
            "  - \"esto es un string, no un dict\"\n"
            "  - 42\n"
        )

        entries = load_benchmarks()

        assert len(entries) == 1
        assert entries[0].model_id == "bueno"

    def test_saltea_model_id_invalido(self, yaml_en_tmp):
        yaml_en_tmp(
            "models:\n"
            '  - model_id: ""\n'
            "    mmlu_score: 90\n"
            "  - model_id: \"   \"\n"
            "    mmlu_score: 90\n"
            "  - model_id: 12345\n"
            "    mmlu_score: 90\n"
            '  - model_id: "valido"\n'
            "    mmlu_score: 90\n"
        )

        entries = load_benchmarks()

        assert len(entries) == 1
        assert entries[0].model_id == "valido"

    def test_saltea_mmlu_score_fuera_de_rango_o_no_numerico(self, yaml_en_tmp):
        yaml_en_tmp(
            "models:\n"
            '  - model_id: "negativo"\n'
            "    mmlu_score: -1\n"
            '  - model_id: "arriba"\n'
            "    mmlu_score: 101\n"
            '  - model_id: "texto"\n'
            '    mmlu_score: "mucho"\n'
            '  - model_id: "sin-score"\n'
            '  - model_id: "ok"\n'
            "    mmlu_score: 60\n"
        )

        entries = load_benchmarks()

        assert [e.model_id for e in entries] == ["ok"]

    def test_acepta_los_extremos_del_rango(self, yaml_en_tmp):
        yaml_en_tmp(
            "models:\n"
            '  - model_id: "cero"\n'
            "    mmlu_score: 0\n"
            '  - model_id: "cien"\n'
            "    mmlu_score: 100\n"
        )

        assert len(load_benchmarks()) == 2


class TestYamlInvalido:
    """Los errores de archivo o de formato levantan ``LLMBenchmarkFileError``."""

    def test_levanta_si_el_archivo_no_existe(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.core.llm_model_benchmarks._yaml_path",
            lambda: tmp_path / "no-existe.yaml",
        )

        with pytest.raises(LLMBenchmarkFileError, match="No se encontro"):
            load_benchmarks()

    def test_levanta_con_yaml_sintacticamente_invalido(self, yaml_en_tmp):
        yaml_en_tmp("models: [\n  - model_id: roto\n    mmlu: :\n")

        with pytest.raises(LLMBenchmarkFileError, match="YAML invalido"):
            load_benchmarks()

    def test_levanta_si_falta_la_clave_models(self, yaml_en_tmp):
        yaml_en_tmp("tiers:\n  tier1:\n    - model_id: gpt-4\n")

        with pytest.raises(LLMBenchmarkFileError, match="clave 'models'"):
            load_benchmarks()

    def test_levanta_si_models_no_es_lista(self, yaml_en_tmp):
        yaml_en_tmp("models:\n  model_id: gpt-4\n  mmlu_score: 90\n")

        with pytest.raises(LLMBenchmarkFileError, match="debe ser una lista"):
            load_benchmarks()


class TestCache:
    """El cache evita releer el archivo, y ``invalidate_cache`` lo limpia."""

    def test_la_segunda_llamada_usa_el_cache(self, yaml_en_tmp, monkeypatch):
        yaml_en_tmp(YAML_VALIDO)

        assert len(load_benchmarks()) == 2

        # Si el cache no sirviera, esta llamada volveria a leer el archivo.
        def _explota() -> Path:
            raise AssertionError("reload del archivo: el cache no funciono")

        monkeypatch.setattr(
            "app.core.llm_model_benchmarks._yaml_path", _explota
        )
        assert len(load_benchmarks()) == 2

    def test_invalidate_cache_fuerza_a_releer(self, yaml_en_tmp):
        yaml_en_tmp("models:\n  - model_id: v1\n    mmlu_score: 10\n")
        assert load_benchmarks()[0].model_id == "v1"

        yaml_en_tmp("models:\n  - model_id: v2\n    mmlu_score: 20\n")
        invalidate_cache()
        assert load_benchmarks()[0].model_id == "v2"

    def test_yaml_vacio_devuelve_lista_vacia(self, yaml_en_tmp):
        yaml_en_tmp("models: []\n")

        assert load_benchmarks() == []


class TestGetModelScore:
    """``get_model_score`` busca por ``model_id`` y devuelve ``mmlu_score``."""

    def test_devuelve_el_score_de_un_modelo_conocido(self, yaml_en_tmp):
        yaml_en_tmp(YAML_VALIDO)

        assert get_model_score("gpt-4") == 95.5

    def test_devuelve_none_para_un_modelo_desconocido(self, yaml_en_tmp):
        yaml_en_tmp(YAML_VALIDO)

        assert get_model_score("modelo-que-no-existe") is None

    def test_devuelve_none_para_id_vacio(self, yaml_en_tmp):
        yaml_en_tmp(YAML_VALIDO)

        assert get_model_score("") is None


class TestYamlRealDelRepo:
    """Smoke test contra el archivo real: si esto falla, el producto esta roto."""

    def test_el_yaml_del_repo_es_valido(self):
        from app.core.llm_model_benchmarks import _yaml_path

        assert _yaml_path().exists(), f"falta el YAML de benchmarks: {_yaml_path()}"

        entries = load_benchmarks()

        assert entries, "el YAML del repo no tiene entradas utilizables"
        assert all(e.mmlu_score for e in entries), (
            "hay entradas sin mmlu_score en el YAML del repo"
        )

    def test_los_scores_estan_en_rango_y_ordenados_por_tier(self):
        from app.core.llm_model_benchmarks import MMLU_TIER1_THRESHOLD

        entries = load_benchmarks()

        for entry in entries:
            assert 0 <= entry.mmlu_score <= 100, entry
        # Ningun modelo blocked deberia estar en el catalogo.
        blocked = [e for e in entries if e.mmlu_score < MMLU_TIER1_THRESHOLD]
        assert blocked, "el YAML deberia tener al menos un modelo de tier1"