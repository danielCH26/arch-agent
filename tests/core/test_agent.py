"""
Tests para ArchitectAgent de F08.

Issue: #12

Nota: no requieren LLM real — mockean build_langchain_model.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.agent import (
    AgentState,
    ArchitectAgent,
    parse_proposal_text,
    _node_retrieve_context,
    _node_build_prompt,
    _node_format_proposal,
    SYSTEM_PROMPT,
    PROPOSAL_SECTIONS,
)


VALID_PROPOSAL = """# Propuesta e-commerce
## Componentes
- API Gateway
- Servicio de productos
## Tecnologías
- FastAPI
## Patrones
- Microservicios
## Justificación
Escala bien.
"""

GENERAL_QUESTION = "¿Qué es un monolito?"


# =============================================================================
# Tests de parse_proposal_text
# =============================================================================


class TestParseProposalText:
    def test_valid_proposal_parses(self):
        result = parse_proposal_text(VALID_PROPOSAL)
        assert result is not None
        assert "API Gateway" in result["components"]
        assert "FastAPI" in result["technologies"]
        assert "Microservicios" in result["patterns"]
        assert "Escala" in result["rationale"]
        assert result["raw_text"] == VALID_PROPOSAL

    def test_general_question_returns_none(self):
        assert parse_proposal_text(GENERAL_QUESTION) is None

    def test_empty_text_returns_none(self):
        assert parse_proposal_text("") is None

    def test_one_section_only_returns_none(self):
        # Con una sola sección no alcanza el umbral (>=2)
        assert parse_proposal_text("## Componentes\n- API") is None

    def test_title_extraction(self):
        result = parse_proposal_text(VALID_PROPOSAL)
        assert result["title"].startswith("Propuesta e-commerce")

    def test_case_insensitive_sections(self):
        text = "## componentes\n- X\n## tecnologías\n- Y\n## patrones\n- Z\n## justificación\n- W"
        result = parse_proposal_text(text)
        assert result is not None
        assert "X" in result["components"]


# =============================================================================
# Tests de nodos
# =============================================================================


class TestNodeRetrieveContext:
    def test_populates_rag_documents(self):
        state = {
            "messages": [HumanMessage(content="necesito propuesta")],
            "user_id": 1,
            "project_id": None,
        }
        with patch("app.core.agent.retrieve_context") as mock_retrieve:
            mock_retrieve.return_value = [
                Document(page_content="doc content", metadata={"source": "user_document"})
            ]
            result = _node_retrieve_context(state)
            assert len(result["rag_documents"]) == 1
            mock_retrieve.assert_called_once()

    def test_empty_query_uses_last_human_message(self):
        state = {
            "messages": [
                HumanMessage(content="primera pregunta"),
                AIMessage(content="respuesta"),
                HumanMessage(content="segunda pregunta"),
            ],
            "user_id": 1,
        }
        with patch("app.core.agent.retrieve_context") as mock_retrieve:
            _node_retrieve_context(state)
            # La query debe ser el último mensaje humano
            assert mock_retrieve.call_args.kwargs["query"] == "segunda pregunta"


class TestNodeBuildPrompt:
    def test_inserts_system_message_first(self):
        state = {
            "messages": [HumanMessage(content="hola")],
            "rag_documents": [],
            "project_context": "Proyecto X",
        }
        result = _node_build_prompt(state)
        messages = result["messages"]
        assert isinstance(messages[0], SystemMessage)
        assert SYSTEM_PROMPT in messages[0].content
        assert "Proyecto X" in messages[0].content

    def test_includes_rag_context(self):
        state = {
            "messages": [HumanMessage(content="hola")],
            "rag_documents": [Document(page_content="doc importante", metadata={})],
            "project_context": "",
        }
        result = _node_build_prompt(state)
        assert "doc importante" in result["messages"][0].content


class TestNodeFormatProposal:
    def test_sets_proposal_when_parseable(self):
        state = {"response_text": VALID_PROPOSAL}
        result = _node_format_proposal(state)
        assert result["proposal"] is not None
        assert result["proposal"]["components"]

    def test_sets_none_when_not_parseable(self):
        state = {"response_text": GENERAL_QUESTION}
        result = _node_format_proposal(state)
        assert result["proposal"] is None


# =============================================================================
# Tests de ArchitectAgent (con mocks de LLM y RAG)
# =============================================================================


class TestArchitectAgent:
    @pytest.fixture
    def mock_model(self):
        model = MagicMock()
        model.ainvoke = AsyncMock(
            return_value=AIMessage(content=GENERAL_QUESTION + " Es un patrón de software.")
        )
        with patch("app.core.agent.build_langchain_model", return_value=model):
            yield model

    @pytest.fixture
    def agent(self, mock_model):
        with patch("app.core.agent.retrieve_context", return_value=[]):
            agent = ArchitectAgent(user_id=1, project_id=None)
            yield agent

    def test_agent_instantiates_per_request(self, agent):
        """R13: cada instancia es independiente."""
        agent2 = ArchitectAgent(user_id=2, project_id=None)
        assert agent is not agent2

    def test_agent_builds_graph(self, agent):
        assert agent.graph is not None

    @pytest.mark.asyncio
    async def test_invoke_returns_response(self, agent, mock_model):
        with patch("app.core.agent.retrieve_context", return_value=[]):
            result = await agent.invoke("¿Qué es un monolito?")
            assert "response_text" in result
            assert "monolito" in result["response_text"].lower()

    @pytest.mark.asyncio
    async def test_invoke_with_proposal(self, agent, mock_model):
        mock_model.ainvoke = AsyncMock(
            return_value=AIMessage(content=VALID_PROPOSAL)
        )
        with patch("app.core.agent.retrieve_context", return_value=[]):
            result = await agent.invoke("necesito propuesta")
            assert result["proposal"] is not None
            assert result["proposal"]["components"]

    @pytest.mark.asyncio
    async def test_stream_yields_tokens(self, agent, mock_model):
        """stream() debe yield de eventos con type=token."""
        mock_model.ainvoke = AsyncMock(
            return_value=AIMessage(content=GENERAL_QUESTION)
        )
        with patch("app.core.agent.retrieve_context", return_value=[]):
            events = []
            async for event in agent.stream("¿Qué es un monolito?"):
                events.append(event)
                if event["type"] == "done":
                    break

            assert any(e["type"] == "token" for e in events)

    @pytest.mark.asyncio
    async def test_llm_non_transient_error_raises(self, agent, mock_model):
        """R3: errores no transitorios (auth) no reintentan."""
        mock_model.ainvoke = AsyncMock(side_effect=ValueError("invalid api key"))
        with patch("app.core.agent.retrieve_context", return_value=[]):
            with pytest.raises(ValueError, match="invalid api key"):
                await agent.invoke("test")

    @pytest.mark.asyncio
    async def test_missing_model_raises(self):
        """El nodo call_llm requiere un modelo (no None)."""
        from app.core.agent import _make_call_llm_node
        node = _make_call_llm_node(None)
        state = {"messages": [HumanMessage(content="test")]}
        with pytest.raises((AttributeError, ValueError)):
            await node(state)
