"""
F19 -- tests de integracion: cancelacion durante el guardado de una propuesta.

Los tests de ``test_proposal_generator.py`` prueban la logica del ``cancel_event``
con ``MagicMock`` sobre ``SessionLocal``. Aqui se ejerce el MISMO codigo
(``_persist_proposal_and_log`` real) contra PostgreSQL real, para comprobar lo
que los mocks no pueden: que tras cancelar NO quedan filas (ni propuesta, ni
log, ni aprobacion huerfana) y que la iteracion cancelada no se consume.

Tambien se documenta el limite del best-effort: si el ``commit`` ya empezo
cuando llega la cancelacion, la propuesta queda guardada.

Requiere PostgreSQL con pgvector (en CI: el servicio ``postgres`` de ci.yml).
Sin base de datos se omiten, salvo en CI (variable ``CI``), donde fallan para
que un servicio caido no pase desapercibido.
"""

import asyncio
import os
import threading
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import app.models  # noqa: F401  # registrar todos los modelos antes de create_all
from app.core import proposal_generator as gen
from app.core.database import Base, SessionLocal, engine
from app.models.interaction_log import InteractionLog
from app.models.project import Project
from app.models.proposal import Proposal
from app.models.proposal_approval import ProposalApproval
from app.models.session import UserSession
from app.models.user import User


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module", autouse=True)
def _database():
    """Crea las tablas; omite el modulo si no hay Postgres (y no estamos en CI)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        Base.metadata.create_all(engine)
    except OperationalError as exc:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"PostgreSQL no disponible: {exc.__class__.__name__}")
    yield


@pytest.fixture
def world():
    """Usuario + proyecto + sesion reales; se borran al terminar."""
    suffix = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        user = User(
            username=f"cancel_it_{suffix}",
            email=f"cancel_it_{suffix}@example.com",
            password_hash="hashed",
        )
        db.add(user)
        db.flush()
        project = Project(user_id=user.id, name="Biblioteca", current_phase="propuesta")
        db.add(project)
        db.flush()
        session = UserSession(user_id=user.id, project_id=project.id, active_phase="propuesta")
        db.add(session)
        db.commit()
        ids = SimpleNamespace(user_id=user.id, project_id=project.id, session_id=session.id)
    finally:
        db.close()

    yield ids

    db = SessionLocal()
    try:
        # proposals.session_id no tiene ON DELETE: se borran antes que la sesion.
        db.query(Proposal).filter(Proposal.project_id == ids.project_id).delete()
        db.query(User).filter(User.id == ids.user_id).delete()  # cascade: proyecto, sesion, logs
        db.commit()
    finally:
        db.close()


def _persist_kwargs(world, **overrides):
    kwargs = dict(
        session_id=world.session_id,
        project_id=world.project_id,
        iteration=None,
        prior_iteration=0,
        prior_proposal_id=None,
        prior_content=None,
        markdown="## Componentes\n- API",
        citations=[],
        feedback=None,
    )
    kwargs.update(overrides)
    return kwargs


def _count(model, world):
    """Cuenta filas con una sesion NUEVA (no la que hizo el guardado)."""
    db = SessionLocal()
    try:
        return db.execute(
            select(func.count()).select_from(model).where(model.project_id == world.project_id)
        ).scalar_one()
    finally:
        db.close()


def _approvals(proposal_id):
    db = SessionLocal()
    try:
        return db.execute(
            select(func.count())
            .select_from(ProposalApproval)
            .where(ProposalApproval.proposal_id == proposal_id)
        ).scalar_one()
    finally:
        db.close()


def _iterations(world):
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Proposal.iteration)
            .where(Proposal.project_id == world.project_id)
            .order_by(Proposal.iteration)
        ).scalars()
        return list(rows)
    finally:
        db.close()


# =============================================================================
# _persist_proposal_and_log contra Postgres real
# =============================================================================


def test_baseline_persist_commits_proposal_and_log(world):
    proposal_id, interaction_id, iteration = gen._persist_proposal_and_log(
        cancel_event=threading.Event(), **_persist_kwargs(world)
    )

    assert iteration == 1
    assert proposal_id and interaction_id
    assert _count(Proposal, world) == 1
    assert _count(InteractionLog, world) == 1


def test_cancel_before_commit_leaves_no_rows(world):
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(gen._PersistCancelled):
        gen._persist_proposal_and_log(cancel_event=cancel_event, **_persist_kwargs(world))

    assert _count(Proposal, world) == 0
    assert _count(InteractionLog, world) == 0


def test_cancel_arriving_mid_transaction_is_still_caught(world, monkeypatch):
    """La cancelacion llega con las filas ya en flush, antes del commit."""
    cancel_event = threading.Event()

    def _build_prompt_then_cancel(**_kw):
        cancel_event.set()  # el cliente cancela mientras el hilo esta en la BD
        return "prompt"

    monkeypatch.setattr(gen, "_build_prompt", _build_prompt_then_cancel)

    with pytest.raises(gen._PersistCancelled):
        gen._persist_proposal_and_log(cancel_event=cancel_event, **_persist_kwargs(world))

    assert _count(Proposal, world) == 0
    assert _count(InteractionLog, world) == 0


def test_cancelled_save_does_not_consume_an_iteration(world):
    """Lo importante para PROPOSAL_MAX_ITER: el cancelado no ocupa un numero."""
    gen._persist_proposal_and_log(cancel_event=threading.Event(), **_persist_kwargs(world))

    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(gen._PersistCancelled):
        gen._persist_proposal_and_log(cancel_event=cancelled, **_persist_kwargs(world))

    _, _, next_iteration = gen._persist_proposal_and_log(
        cancel_event=threading.Event(), **_persist_kwargs(world)
    )

    assert next_iteration == 2
    assert _iterations(world) == [1, 2]


def test_cancelled_modify_leaves_no_orphan_approval_and_keeps_prior(world):
    first_id, _, _ = gen._persist_proposal_and_log(
        cancel_event=threading.Event(), **_persist_kwargs(world, markdown="v1")
    )
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(gen._PersistCancelled):
        gen._persist_proposal_and_log(
            cancel_event=cancelled,
            **_persist_kwargs(
                world,
                iteration=2,
                prior_iteration=1,
                prior_proposal_id=first_id,
                prior_content="v1",
                markdown="v2",
                feedback="cambia algo",
            ),
        )

    assert _iterations(world) == [1]
    assert _approvals(first_id) == 0  # sin fila "modified" huerfana
    assert _count(InteractionLog, world) == 1  # solo el log de la iteracion 1


def test_commit_already_started_is_not_undone(world, monkeypatch):
    """Limite documentado (best-effort): cancelar DURANTE el commit no lo deshace."""
    cancel_event = threading.Event()
    real_commit = Session.commit

    def _commit_with_late_cancel(self):
        cancel_event.set()  # llega cuando el commit ya esta en marcha
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", _commit_with_late_cancel)

    result = gen._persist_proposal_and_log(cancel_event=cancel_event, **_persist_kwargs(world))

    assert result[2] == 1
    assert _count(Proposal, world) == 1  # por eso el front resincroniza con /latest


# =============================================================================
# Generador completo (stream) + guardado real
# =============================================================================


class _Chunk:
    def __init__(self, content, metadata=None):
        self.content = content
        self.response_metadata = metadata or {}


_PROPOSAL_MD = """## Componentes
- API Layer - FastAPI
- Persistence Layer - PostgreSQL

## Tecnologias
- Lenguaje: Python

## Patrones
- Patron principal: Arquitectura en capas (Layered)

## Justificación del patrón principal
- Motivo de elección: ...
- Reflejo en la arquitectura: ...
- Beneficio esperado: ...
- Riesgo o costo: ...
"""


class _Model:
    async def astream(self, _prompt):
        yield _Chunk(_PROPOSAL_MD)
        yield _Chunk("", {"finish_reason": "stop"})


async def _noop_async(*_a, **_kw):
    return None


def _generator_with_real_persist(world, wrapped_persist):
    """ProposalGenerator real; solo lo externo (LLM, RAG, Engram) esta parcheado."""
    project = SimpleNamespace(name="Biblioteca", description="d")
    stack = ExitStack()
    stack.enter_context(
        patch.object(gen, "_load_project_and_session", return_value=(project, world.session_id))
    )
    stack.enter_context(patch.object(gen, "load_requirements_text", return_value=""))
    stack.enter_context(patch.object(gen, "load_documents_text", return_value=("", [])))
    stack.enter_context(patch.object(gen, "_retrieve_patterns", return_value=[]))
    stack.enter_context(patch.object(gen, "build_langchain_model", return_value=_Model()))
    stack.enter_context(patch.object(gen, "_engram_mirror", new=_noop_async))
    stack.enter_context(
        patch.object(gen, "_persist_proposal_and_log", side_effect=wrapped_persist)
    )
    return stack, gen.ProposalGenerator(user_id=world.user_id, project_id=world.project_id)


def _slow_real_persist():
    """Envuelve el guardado real: espera a que el generador marque el evento."""
    real = gen._persist_proposal_and_log
    started, finished, outcome = threading.Event(), threading.Event(), {}

    def _wrapped(**kw):
        started.set()
        kw["cancel_event"].wait(timeout=5)  # simula la BD ocupada hasta la cancelacion
        try:
            outcome["result"] = real(**kw)
            return outcome["result"]
        except BaseException as exc:  # noqa: BLE001 - se inspecciona en el test
            outcome["error"] = exc
            raise
        finally:
            finished.set()

    return _wrapped, started, finished, outcome


def test_client_cancel_while_saving_persists_nothing(world):
    wrapped, started, finished, outcome = _slow_real_persist()
    stack, generator = _generator_with_real_persist(world, wrapped)

    async def _run():
        async def _consume():
            async for _ in generator.generate_stream():
                pass

        task = asyncio.create_task(_consume())
        assert await asyncio.get_running_loop().run_in_executor(None, started.wait, 5), (
            "el guardado nunca empezo: la propuesta de prueba no pasa la validacion"
        )
        task.cancel()  # el usuario pulsa "Cancelar" con el hilo ya guardando
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.get_running_loop().run_in_executor(None, finished.wait, 5)

    with stack:
        asyncio.run(_run())

    assert finished.is_set()
    assert isinstance(outcome.get("error"), gen._PersistCancelled)
    assert _count(Proposal, world) == 0
    assert _count(InteractionLog, world) == 0


def test_time_budget_exhausted_while_saving_persists_nothing(world, monkeypatch):
    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0.5)
    wrapped, started, finished, outcome = _slow_real_persist()
    stack, generator = _generator_with_real_persist(world, wrapped)

    async def _run():
        return [event async for event in generator.generate_stream()]

    with stack:
        events = asyncio.run(_run())
    assert finished.wait(timeout=5)

    assert events[-1][0] == "error"
    assert isinstance(outcome.get("error"), gen._PersistCancelled)
    assert _count(Proposal, world) == 0
    assert _count(InteractionLog, world) == 0


def test_uncancelled_stream_persists_through_the_real_save(world):
    """Control: el mismo montaje, sin cancelar, si guarda (descarta falsos verdes)."""
    real = gen._persist_proposal_and_log
    stack, generator = _generator_with_real_persist(world, lambda **kw: real(**kw))

    async def _run():
        return [event async for event in generator.generate_stream()]

    with stack:
        events = asyncio.run(_run())

    assert events[-1][0] == "done"
    assert _iterations(world) == [1]
    assert _count(InteractionLog, world) == 1
