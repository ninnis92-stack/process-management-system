import json
from app.extensions import db
from app.models import Workflow
from app.requests_bp.workflow import transition_allowed


def test_workflow_spec_transitions(app):
    with app.app_context():
        # ensure no active workflows
        Workflow.query.delete()
        db.session.commit()

        # legacy behavior: B can move NEW_FROM_A -> B_IN_PROGRESS
        assert transition_allowed('B', 'NEW_FROM_A', 'B_IN_PROGRESS') is True

        # create a department-scoped workflow that only allows a single transition
        spec = {
            "transitions": [
                {"from": "NEW_FROM_A", "to": "UNDER_REVIEW"}
            ]
        }
        wf = Workflow(name='DeptB Simple', department_code='B', spec=spec, active=True)
        db.session.add(wf)
        db.session.commit()

        # Now the legacy allowed transition should be disallowed because workflow overrides
        assert transition_allowed('B', 'NEW_FROM_A', 'B_IN_PROGRESS') is False
        assert transition_allowed('B', 'NEW_FROM_A', 'UNDER_REVIEW') is True

        # Clean up
        db.session.delete(wf)
        db.session.commit()
