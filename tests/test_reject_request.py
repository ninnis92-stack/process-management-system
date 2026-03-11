from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import Comment, RejectRequestConfig
from app.models import Request as ReqModel
from app.models import User


def _login(client, email="b_assignee@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_reject_request_requires_reason_and_closes(app, client):
    with app.app_context():
        u = User(
            email="b_assignee@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        submitter = User(
            email="submitter@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
        )
        db.session.add_all([u, submitter])
        db.session.commit()

        req = ReqModel(
            title="Needs rejection",
            request_type="both",
            pricebook_status="unknown",
            description="desc",
            priority="high",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            created_by_user_id=submitter.id,
            assigned_to_user_id=u.id,
            due_at=(datetime.utcnow() + timedelta(days=2)),
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id

    rv = _login(client)
    assert rv.status_code == 200

    # Reject without reason should fail
    rv = client.post(
        f"/requests/{req_id}/reject", data={"reject_reason": ""}, follow_redirects=True
    )
    assert rv.status_code == 200
    assert b"reason is required" in rv.data.lower()

    # Reject with reason should close request and create public comment
    rv = client.post(
        f"/requests/{req_id}/reject",
        data={"reject_reason": "Invalid donor mapping"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"rejected and closed" in rv.data.lower()

    with app.app_context():
        fresh = db.session.get(ReqModel, req_id)
        assert fresh.status == "CLOSED"
        c = (
            Comment.query.filter_by(request_id=req_id, visibility_scope="public")
            .order_by(Comment.id.desc())
            .first()
        )
        assert c is not None
        assert "Invalid donor mapping" in c.body


def test_reject_config_defaults_to_dept_b_only(app):
    with app.app_context():
        cfg = RejectRequestConfig.get()
        assert cfg.enabled is True
        assert cfg.dept_b_enabled is True
        assert cfg.dept_a_enabled is False
        assert cfg.dept_c_enabled is False
        assert (cfg.button_label or "").lower() == "deny request"
