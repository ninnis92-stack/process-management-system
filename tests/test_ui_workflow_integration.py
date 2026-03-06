from werkzeug.security import generate_password_hash
from app.extensions import db
from app.models import User, Workflow, Request as ReqModel
from datetime import datetime, timedelta


def test_request_detail_shows_workflow_limited_transitions(app, client):
    with app.app_context():
        # Create a Dept B workflow that only allows a couple transitions from B_IN_PROGRESS
        spec = {
            "steps": [
                {"code": "B_FINAL_REVIEW", "label": "Final Review"},
                {"code": "WAITING_ON_A_RESPONSE", "label": "Waiting on A"},
            ],
            "transitions": [
                {"from": "B_IN_PROGRESS", "to": "B_FINAL_REVIEW"},
                {"from": "B_IN_PROGRESS", "to": "WAITING_ON_A_RESPONSE"},
            ],
        }
        wf = Workflow(name="B Simple", department_code="B", spec=spec, active=True)
        db.session.add(wf)

        # Create a Dept B user
        b = User(email='b_user2@example.com', password_hash=generate_password_hash('secret'), department='B', is_active=True)
        db.session.add(b)
        db.session.commit()

        # Create a request in B_IN_PROGRESS owned by Dept B
        r = ReqModel(
            title='Integration Test',
            request_type='both',
            pricebook_status='unknown',
            description='x',
            priority='medium',
            status='B_IN_PROGRESS',
            owner_department='B',
            submitter_type='user',
            due_at=(datetime.utcnow() + timedelta(days=2)),
        )
        r.created_by_user_id = b.id
        db.session.add(r)
        db.session.commit()
        rid = r.id

    # login as B and view request_detail
    rv = client.post('/auth/login', data={'email': 'b_user2@example.com', 'password': 'secret'}, follow_redirects=True)
    assert rv.status_code == 200
    resp = client.get(f'/requests/{rid}')
    assert resp.status_code == 200
    html = resp.data.decode('utf-8')

    # Assert that only the workflow-allowed transitions appear in the select
    assert 'value="B_FINAL_REVIEW"' in html
    assert 'Final Review' in html
    assert 'value="WAITING_ON_A_RESPONSE"' in html
    # Label may come from the workflow spec or be replaced by a legacy
    # friendly label; accept either.
    assert ('Waiting on A' in html) or ('Pending review from Department A' in html)
    # A transition not in the workflow should not be present
    assert 'value="SENT_TO_A"' not in html
    assert 'value="C_APPROVED"' not in html

    # handoffTargetsData is included in the template when handoff hints exist; UI JS will read it.
