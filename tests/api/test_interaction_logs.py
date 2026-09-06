from app.models import Approval, InteractionLog, Proposal


def test_interaction_log_models_import_with_foreign_keys():
    assert InteractionLog.__table__.c.session_id.foreign_keys
    assert InteractionLog.__table__.c.project_id.foreign_keys
    assert Approval.__table__.c.proposal_id.foreign_keys
    assert Proposal.__table__.c.session_id.foreign_keys
