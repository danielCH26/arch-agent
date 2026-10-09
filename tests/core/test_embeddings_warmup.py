"""F19: singleton de embeddings thread-safe + warm-up de arranque.

No carga el modelo real: se sustituye ``HuggingFaceEmbeddings`` por un doble.
"""

import threading
import time
from unittest.mock import patch

import pytest

from app.core import embeddings as emb


@pytest.fixture(autouse=True)
def _fresh_singleton():
    """Cada test parte sin modelo cargado y deja el estado como estaba."""
    previous = emb._instance
    emb._instance = None
    yield
    emb._instance = previous


def test_concurrent_callers_load_the_model_only_once():
    """Warm-up y primera busqueda RAG a la vez: una sola carga, misma instancia."""
    constructed = []
    release = threading.Event()

    def _slow_constructor(**kwargs):
        constructed.append(kwargs)
        release.wait(timeout=5)  # mantiene la carga "en curso" mientras llegan los demas
        return object()

    results = []

    def _caller():
        results.append(emb.get_embeddings())

    with patch.object(emb, "HuggingFaceEmbeddings", side_effect=_slow_constructor):
        threads = [threading.Thread(target=_caller) for _ in range(8)]
        for t in threads:
            t.start()
        time.sleep(0.2)  # da tiempo a que todos lleguen a get_embeddings()
        release.set()
        for t in threads:
            t.join(timeout=5)

    assert len(constructed) == 1
    assert len(results) == 8
    assert len({id(r) for r in results}) == 1


def test_get_embeddings_returns_the_cached_instance_afterwards():
    with patch.object(emb, "HuggingFaceEmbeddings", side_effect=lambda **_: object()) as ctor:
        first = emb.get_embeddings()
        second = emb.get_embeddings()

    assert first is second
    assert ctor.call_count == 1


def test_a_failed_load_is_not_cached_and_the_next_call_retries():
    attempts = []

    def _flaky(**_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("sin red")
        return object()

    with patch.object(emb, "HuggingFaceEmbeddings", side_effect=_flaky):
        with pytest.raises(RuntimeError):
            emb.get_embeddings()
        model = emb.get_embeddings()

    assert model is not None
    assert len(attempts) == 2


def test_warmup_preloads_the_model_so_the_first_real_call_does_not_load_it():
    with patch.object(emb, "HuggingFaceEmbeddings", side_effect=lambda **_: object()) as ctor:
        assert emb.warmup_embeddings() is True
        assert ctor.call_count == 1

        emb.get_embeddings()  # la "primera busqueda RAG"

    assert ctor.call_count == 1


def test_warmup_never_raises_when_the_model_cannot_be_loaded():
    with patch.object(emb, "HuggingFaceEmbeddings", side_effect=RuntimeError("sin red")):
        assert emb.warmup_embeddings() is False


def test_a_failed_warmup_does_not_block_a_later_real_load():
    with patch.object(emb, "HuggingFaceEmbeddings", side_effect=RuntimeError("sin red")):
        emb.warmup_embeddings()

    with patch.object(emb, "HuggingFaceEmbeddings", side_effect=lambda **_: object()):
        assert emb.get_embeddings() is not None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),  # default: on
        ("on", True),
        ("true", True),
        ("off", False),
        ("OFF", False),
        (" off ", False),
        ("0", False),
        ("false", False),
        ("no", False),
    ],
)
def test_warmup_enabled_flag(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("EMBEDDINGS_WARMUP", raising=False)
    else:
        monkeypatch.setenv("EMBEDDINGS_WARMUP", value)

    assert emb.warmup_enabled() is expected
