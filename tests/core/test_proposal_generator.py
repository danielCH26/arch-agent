from app.core.proposal_generator import ProposalGenerator


def test_generate_sync_returns_proposal_skeleton():
    result = ProposalGenerator().generate_sync(42)
    assert result["project_id"] == 42
    assert set(result["content"]) == {"componentes", "tecnologias", "patrones"}
    assert result["citations"] == []
    assert result["lifecycle"] == "proposed"
