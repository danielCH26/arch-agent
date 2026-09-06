"""Proposal generation boundary.

The persistence contract follows ADR-008 and the eventual SSE transport follows
ADR-009. Streaming is intentionally deferred to slice 2.
"""


class ProposalGenerator:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def generate_stream(self, project_id: int, feedback: str | None = None):
        # slice 2 will implement this
        raise NotImplementedError("streaming wired in slice 2")

    def generate_sync(self, project_id: int) -> dict:
        """Return the stable proposal skeleton until the LLM pipeline lands."""
        return {
            "project_id": project_id,
            "content": {"componentes": [], "tecnologias": [], "patrones": []},
            "citations": [],
            "feedback": None,
            "lifecycle": "proposed",
        }
