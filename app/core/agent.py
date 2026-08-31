"""
ArchitectAgent (F08): agente LangGraph que genera propuestas de arquitectura.

Issue: #12

Flujo (StateGraph):
    retrieve_context → build_prompt → call_llm → format_proposal → END

Riesgos mitigados:
- R13: instancia POR REQUEST (nunca global, nunca singleton)
- R3: retry con backoff en LLM call (timeout/429/5xx)
- R12: CancelledError manejado por el caller (chat.py)
"""

import asyncio
import json
import logging
from typing import Annotated, Any, AsyncIterator, Dict, List, Optional, Sequence, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.core.rag import retrieve_context
from app.core.llm_loader import build_langchain_model

logger = logging.getLogger(__name__)

# Config
HISTORY_LIMIT = 20          # R8: máximo de mensajes de history
LLM_MAX_RETRIES = 2         # R3: retries ante fallo transitorio
LLM_RETRY_BASE_DELAY = 1.5  # segundos


# =============================================================================
# State
# =============================================================================


class AgentState(TypedDict, total=False):
    """Estado del grafo del agente."""
    messages: Annotated[Sequence[BaseMessage], "append"]  # conversación
    user_id: int
    project_id: Optional[int]
    session_id: Optional[int]
    project_context: str          # info del proyecto activo
    rag_documents: List[Document] # resultados del RAG
    response_text: str            # respuesta completa del LLM
    proposal: Optional[Dict[str, Any]]  # propuesta parseada


# =============================================================================
# System prompt
# =============================================================================

SYSTEM_PROMPT = """Eres un arquitecto de software senior con 15+ años de experiencia.
Tu trabajo es ayudar al usuario a definir la arquitectura de su proyecto.

Reglas:
- Basa tus recomendaciones en los patrones y documentos recuperados del RAG.
- SIEMPRE cita qué patrón o documento fundamenta cada decisión.
- Cuando el usuario pida una propuesta, estructura tu respuesta en secciones:
  ## Componentes
  ## Tecnologías
  ## Patrones
  ## Justificación
- Si el usuario hace una pregunta general, responde de forma útil y concisa.
- Responde en el idioma del usuario (español por defecto).
"""


# =============================================================================
# Nodos del grafo
# =============================================================================


def _node_retrieve_context(state: AgentState) -> Dict[str, Any]:
    """Recupera contexto del RAG (docs del usuario + patrones)."""
    messages = state.get("messages", [])
    # La query es el último mensaje humano
    query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            query = msg.content
            break

    docs = retrieve_context(
        user_id=state["user_id"],
        query=query,
        project_id=state.get("project_id"),
    )
    return {"rag_documents": docs}


def _format_rag_context(docs: List[Document]) -> str:
    """Formatea los documentos RAG para inyectar en el prompt."""
    if not docs:
        return "(Sin documentos o patrones relevantes recuperados.)"
    parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "desconocido")
        name = doc.metadata.get("pattern_name") or doc.metadata.get("document_id", "")
        parts.append(f"[{i}] ({source}: {name})\n{doc.page_content}")
    return "\n\n".join(parts)


def _node_build_prompt(state: AgentState) -> Dict[str, Any]:
    """Construye el prompt final: system + project context + RAG."""
    rag_context = _format_rag_context(state.get("rag_documents", []))
    project_context = state.get("project_context") or "(Sin proyecto activo)"

    system_msg = SystemMessage(
        content=SYSTEM_PROMPT
        + f"\n\n## Contexto del proyecto activo\n{project_context}"
        + f"\n\n## Contexto recuperado del RAG\n{rag_context}"
    )

    # Insertar el SystemMessage al inicio de la conversación
    messages = [system_msg] + list(state.get("messages", []))
    return {"messages": messages}


def _make_call_llm_node(model):
    """
    Factory del nodo call_llm con el modelo en closure.

    Evita depender del config de LangGraph (R13: cada agente tiene su nodo).
    Implementa retry con backoff para errores transitorios (R3).
    """

    async def call_llm(state: AgentState) -> Dict[str, Any]:
        messages = state.get("messages", [])

        last_error: Optional[Exception] = None
        for attempt in range(LLM_MAX_RETRIES + 1):
            try:
                response = await model.ainvoke(messages)
                return {"response_text": response.content or ""}
            except (TimeoutError, ConnectionError) as e:
                last_error = e
                logger.warning("LLM call attempt %d failed (transient): %s", attempt + 1, e)
            except Exception as e:
                # Errores no transitorios (auth, bad request) no reintentan
                logger.error("LLM call failed (non-transient): %s", e)
                raise

            if attempt < LLM_MAX_RETRIES:
                await asyncio.sleep(LLM_RETRY_BASE_DELAY * (2 ** attempt))

        raise last_error or RuntimeError("LLM call failed after retries")

    return call_llm


# =============================================================================
# Parseo de propuestas
# =============================================================================

PROPOSAL_SECTIONS = ["Componentes", "Tecnologías", "Patrones", "Justificación"]


def parse_proposal_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Intenta parsear la respuesta del LLM como propuesta estructurada.

    Busca las 4 secciones esperadas (## Componentes, etc.).
    Retorna None si no parece una propuesta (pregunta general, etc.).
    """
    if not text:
        return None

    sections: Dict[str, str] = {}
    current: Optional[str] = None
    lines: Dict[str, List[str]] = {s: [] for s in PROPOSAL_SECTIONS}

    for line in text.splitlines():
        header = line.strip().lstrip("#").strip().lower()
        matched = None
        for section in PROPOSAL_SECTIONS:
            if header == section.lower() or header.startswith(section.lower()):
                matched = section
                break
        if matched:
            current = matched
            continue
        if current:
            lines[current].append(line)

    for section in PROPOSAL_SECTIONS:
        content = "\n".join(lines[section]).strip()
        if content:
            sections[section] = content

    # Es propuesta solo si tiene al menos 2 de las 4 secciones
    if len(sections) >= 2:
        # Extraer título: primera línea no vacía del texto
        title = next((l.strip().lstrip("#").strip() for l in text.splitlines() if l.strip()), "Propuesta de arquitectura")
        return {
            "title": title[:200],
            "components": sections.get("Componentes", ""),
            "technologies": sections.get("Tecnologías", ""),
            "patterns": sections.get("Patrones", ""),
            "rationale": sections.get("Justificación", ""),
            "raw_text": text,
        }
    return None


def _node_format_proposal(state: AgentState) -> Dict[str, Any]:
    """Parsea la respuesta como propuesta si aplica."""
    proposal = parse_proposal_text(state.get("response_text", ""))
    return {"proposal": proposal}


# =============================================================================
# ArchitectAgent
# =============================================================================


class ArchitectAgent:
    """
    Agente de arquitectura basado en LangGraph.

    IMPORTANTE (R13): instanciar POR REQUEST, nunca global ni singleton.
    El LLM se carga por usuario (HU12) en cada instancia.
    """

    def __init__(self, user_id: int, project_id: Optional[int] = None):
        self.user_id = user_id
        self.project_id = project_id
        self.model = build_langchain_model(user_id)
        self.graph = self._build_graph()

    def _build_graph(self):
        """Construye el StateGraph del agente (modelo en closure)."""
        graph = StateGraph(AgentState)
        graph.add_node("retrieve_context", _node_retrieve_context)
        graph.add_node("build_prompt", _node_build_prompt)
        graph.add_node("call_llm", _make_call_llm_node(self.model))
        graph.add_node("format_proposal", _node_format_proposal)

        graph.add_edge(START, "retrieve_context")
        graph.add_edge("retrieve_context", "build_prompt")
        graph.add_edge("build_prompt", "call_llm")
        graph.add_edge("call_llm", "format_proposal")
        graph.add_edge("format_proposal", END)

        return graph.compile()

    def _initial_state(
        self,
        message: str,
        session_id: Optional[int] = None,
        project_context: str = "",
    ) -> AgentState:
        return AgentState(
            messages=[HumanMessage(content=message)],
            user_id=self.user_id,
            project_id=self.project_id,
            session_id=session_id,
            project_context=project_context,
            rag_documents=[],
            response_text="",
            proposal=None,
        )

    async def stream(
        self,
        message: str,
        session_id: Optional[int] = None,
        project_context: str = "",
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Ejecuta el agente y streamea la respuesta.

        Yields:
            {"type": "token", "content": str}   — chunk de texto
            {"type": "proposal", "proposal": dict|None} — al final, propuesta parseada
            {"type": "done"}                    — fin del stream
        """
        state = self._initial_state(message, session_id, project_context)

        try:
            async for chunk, metadata in self.graph.astream(state, stream_mode="messages"):
                content = getattr(chunk, "content", None)
                if content and isinstance(content, str):
                    yield {"type": "token", "content": content}
        except asyncio.CancelledError:
            # R12: client disconnect — cleanup silencioso
            logger.info("Agent stream cancelled by client")
            raise

        # Después del stream: obtener proposal del estado final
        try:
            final_state = await self.graph.ainvoke(
                self._initial_state(message, session_id, project_context)
            )
            proposal = final_state.get("proposal")
        except Exception as e:
            logger.error("Error re-invoking graph for proposal parse: %s", e)
            proposal = parse_proposal_text("")

        yield {"type": "proposal", "proposal": proposal}
        yield {"type": "done"}

    async def invoke(
        self,
        message: str,
        session_id: Optional[int] = None,
        project_context: str = "",
    ) -> Dict[str, Any]:
        """
        Ejecuta el agente sin streaming. Útil para tests.

        Returns:
            {"response_text": str, "proposal": dict|None}
        """
        state = self._initial_state(message, session_id, project_context)
        final = await self.graph.ainvoke(state)
        return {
            "response_text": final.get("response_text", ""),
            "proposal": final.get("proposal"),
        }
