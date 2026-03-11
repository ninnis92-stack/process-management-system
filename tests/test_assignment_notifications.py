from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import Request as ReqModel
from app.models import User

# reuse helpers from other tests
from tests.test_site_navigation import _login


def test_assigned_user_notified_on_status_change(monkeypatch, app, client):
    # Create two department-B users and a request assigned to the first user.
    with app.app_context():
        assignee = User(
            email="assignee@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        actor = User(
            email="actor@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        db.session.add_all([assignee, actor])
        db.session.flush()

        req = ReqModel(
            title="Flow test",
            request_type="both",
            pricebook_status="unknown",
            description="flow",
            priority="medium",
            status="NEW_FROM_A",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        db.session.add(req)
        db.session.flush()
        # assign right away
        req.assigned_to_user_id = assignee.id
        db.session.commit()

    # log in as the other user who will trigger the transition
    rv = _login(client, "actor@example.com")
    assert rv.status_code == 200

    called = []

    def mock_notify(users, title, **kwargs):
        called.append([u.id for u in users])
        # return nothing like real notify_users

    monkeypatch.setattr("app.requests_bp.routes.notify_users", mock_notify)

    # perform a simple status transition that is allowed for dept B
    rv = client.post(
        f"/requests/{req.id}/transition",
        data={"to_status": "B_IN_PROGRESS"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    # confirm that the assigned user was included in a notification call
    all_ids = [uid for group in called for uid in group]
    assert (
        assignee.id in all_ids
    ), f"Assigned user {assignee.id} should have been notified; got calls {called}"
