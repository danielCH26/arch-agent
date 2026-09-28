"""Tests de app/core/project_context.py y de cómo llega ese contexto al prompt
de la propuesta.

Bug que cubren: la propuesta se generaba solo con el NOMBRE del proyecto -- ni
el resumen de requerimientos aprobado ni los PDF/MD subidos llegaban al prompt,
así que cosas como "en la reunión dijeron que son 8 meses" (dichas en un
documento o en un ajuste al resumen) nunca se reflejaban en la propuesta.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import project_context
from app.core.database import Base
from app.core.proposal_generator import _build_prompt, _build_summary_query

RESUMEN = {
    "problema": "Plataforma de cadena de frío",
    "usuarios": "Operadores 24/7",
    "funcionalidades": ["Alertas automáticas", "Rutas dinámicas"],
    "restricciones": ["MVP en 6 meses", ""],
    "calidad": ["99.99% disponibilidad"],
}


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.models  # noqa: F401

    Base.metadata.tables["users"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["sessions"].create(bind=engine, checkfirst=True)
    # uploaded_documents / document_chunks usan Vector(384) (pgvector), que
    # SQLite no compila: se crean con DDL mínimo equivalente para el test.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE uploaded_documents (id INTEGER PRIMARY KEY, user_id INTEGER, "
            "project_id INTEGER, filename TEXT, file_type TEXT, file_size_bytes INTEGER, "
            "chunk_count INTEGER, processed BOOLEAN, version INTEGER, created_at TIMESTAMP)"
        ))
        conn.execute(text(
            "CREATE TABLE document_chunks (id INTEGER PRIMARY KEY, document_id INTEGER, "
            "chunk_text TEXT, chunk_index INTEGER, embedding TEXT, metadata TEXT, "
            "created_at TIMESTAMP)"
        ))
    Session = sessionmaker(bind=engine)
    with patch.object(project_context, "SessionLocal", Session):
        yield Session, engine
    engine.dispose()


def _add_doc(engine, doc_id, *, user_id=1, project_id=1, filename="acta.md",
             processed=True, chunks=("Plazo: 8 meses.",)):
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO uploaded_documents (id, user_id, project_id, filename, processed, "
            "created_at) VALUES (:i, :u, :p, :f, :pr, datetime('now', :off))"
        ), {"i": doc_id, "u": user_id, "p": project_id, "f": filename, "pr": processed,
            "off": f"+{doc_id} seconds"})
        for idx, chunk in enumerate(chunks):
            conn.execute(text(
                "INSERT INTO document_chunks (document_id, chunk_text, chunk_index) "
                "VALUES (:d, :t, :i)"
            ), {"d": doc_id, "t": chunk, "i": idx})


class TestFormatRequirements:
    def test_formats_all_sections_and_skips_empty_items(self):
        out = project_context.format_requirements_summary(RESUMEN)
        assert "Problema: Plataforma de cadena de frío" in out
        assert "- MVP en 6 meses" in out
        assert "- Alertas automáticas" in out
        assert out.count("\n- ") == 4  # 2 funcionalidades + 1 restricción + 1 calidad; el ítem vacío no cuenta

    @pytest.mark.parametrize("value", [None, {}, "texto", []])
    def test_non_summary_values_give_empty_string(self, value):
        assert project_context.format_requirements_summary(value) == ""


class TestLoadRequirementsText:
    def test_reads_summary_of_the_given_project_only(self, db_session):
        from app.models.session import UserSession

        Session, engine = db_session
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (id, username, email, password_hash) "
                              "VALUES (1, 'u', 'u@x', 'x')"))
        db = Session()
        db.add(UserSession(user_id=1, engram_state={
            "1": {"requerimientos": {"resumen": RESUMEN}},
            "2": {"requerimientos": {"resumen": {"problema": "OTRO PROYECTO"}}},
        }))
        db.commit()
        db.close()

        assert "Plataforma de cadena de frío" in project_context.load_requirements_text(1, 1)
        assert "OTRO PROYECTO" not in project_context.load_requirements_text(1, 1)
        assert project_context.load_requirements_text(1, 99) == ""

    def test_no_session_returns_empty(self, db_session):
        assert project_context.load_requirements_text(1, 1) == ""


class TestLoadDocumentsText:
    def test_includes_processed_docs_of_project_in_order_with_headers(self, db_session):
        _, engine = db_session
        _add_doc(engine, 1, filename="acta.md", chunks=("Reunión: plazo de 8 meses.", "Equipo de 5."))
        _add_doc(engine, 2, filename="notas.md", chunks=("Presupuesto 2500 USD.",))
        _add_doc(engine, 3, project_id=2, filename="otro_proyecto.md", chunks=("NO DEBE SALIR",))
        _add_doc(engine, 4, user_id=2, filename="de_otro_user.md", chunks=("NO DEBE SALIR",))
        _add_doc(engine, 5, filename="pendiente.md", processed=False, chunks=("NO DEBE SALIR",))

        text_out, names = project_context.load_documents_text(1, 1)

        assert names == ["acta.md", "notas.md"]
        assert "### Documento: acta.md" in text_out
        assert "Reunión: plazo de 8 meses.\nEquipo de 5." in text_out
        assert text_out.index("acta.md") < text_out.index("notas.md")
        assert "NO DEBE SALIR" not in text_out

    def test_respects_max_chars(self, db_session):
        _, engine = db_session
        _add_doc(engine, 1, chunks=("x" * 5000,))
        text_out, _ = project_context.load_documents_text(1, 1, max_chars=300)
        assert len(text_out) <= 300 + len("\n[...recortado por tamaño...]")
        assert "recortado" in text_out

    def test_no_docs_returns_empty(self, db_session):
        assert project_context.load_documents_text(1, 1) == ("", [])

    def test_db_failure_returns_empty_instead_of_raising(self):
        with patch.object(project_context, "SessionLocal", side_effect=RuntimeError("db down")):
            assert project_context.load_documents_text(1, 1) == ("", [])


class TestProposalPromptUsesProjectContext:
    def test_prompt_includes_requirements_description_and_documents(self):
        prompt = _build_prompt(
            citations=[], prior_content=None, feedback=None, project_name="SmartCold",
            description="Distribución refrigerada",
            requirements_text="Restricciones:\n- MVP en 6 meses",
            documents_text="### Documento: acta.md\nEn la reunión dijeron que tienen 8 meses.",
        )
        assert "Distribución refrigerada" in prompt
        assert "MVP en 6 meses" in prompt
        assert "tienen 8 meses" in prompt
        assert "prioriza el documento" in prompt
        # el formato obligatorio de 3 secciones no cambia
        assert "## Componentes" in prompt and "## Tecnologias" in prompt and "## Patrones" in prompt

    def test_prompt_without_context_is_unchanged_shape(self):
        prompt = _build_prompt(citations=[], prior_content=None, feedback=None, project_name="P")
        assert "Requerimientos aprobados" not in prompt
        assert "Documentos aportados" not in prompt

    def test_rag_query_includes_requirements(self):
        query = _build_summary_query("P", "desc", None, None, "Restricciones:\n- MVP en 6 meses")
        assert "MVP en 6 meses" in query
