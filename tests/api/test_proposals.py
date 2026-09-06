from app.models import Approval, InteractionLog, Proposal


def test_proposal_models_import_and_constraints_compile():
    assert Proposal.__tablename__ == "proposals"
    assert InteractionLog.__tablename__ == "interaction_logs"
    assert Approval.__tablename__ == "approvals"
    assert Proposal.__table__.c.content.type.__class__.__name__ == "JSONB"
