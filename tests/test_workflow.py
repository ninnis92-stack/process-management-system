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

        # Workflow spec augments legacy transitions; legacy behavior remains allowed
        assert transition_allowed('B', 'NEW_FROM_A', 'B_IN_PROGRESS') is True
        assert transition_allowed('B', 'NEW_FROM_A', 'UNDER_REVIEW') is True

        # Clean up
        db.session.delete(wf)
        db.session.commit()


def test_workflow_spec_override_and_deny(app):
    with app.app_context():
        # ensure no active workflows
        Workflow.query.delete()
        db.session.commit()

        # override mode: spec replaces legacy transitions
        spec_override = {
            "mode": "override",
            "transitions": [
                {"from": "NEW_FROM_A", "to": "UNDER_REVIEW"}
            ]
        }
        wf_o = Workflow(name='DeptB Override', department_code='B', spec=spec_override, active=True)
        db.session.add(wf_o)
        db.session.commit()

        assert transition_allowed('B', 'NEW_FROM_A', 'B_IN_PROGRESS') is False
        assert transition_allowed('B', 'NEW_FROM_A', 'UNDER_REVIEW') is True

        db.session.delete(wf_o)
        db.session.commit()

        # augment mode with deny: remove a legacy transition
        spec_deny = {
            "transitions": [],
            "deny": [["NEW_FROM_A", "B_IN_PROGRESS"]]
        }
        wf_d = Workflow(name='DeptB Deny', department_code='B', spec=spec_deny, active=True)
        db.session.add(wf_d)
        db.session.commit()

        assert transition_allowed('B', 'NEW_FROM_A', 'B_IN_PROGRESS') is False

        db.session.delete(wf_d)
        db.session.commit()
