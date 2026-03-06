import pytest


def test_sent_to_a_clears_assignment_and_notifies(app, client):
    from werkzeug.security import generate_password_hash
    from app.extensions import db
    from app.models import User, Request as ReqModel, AuditLog, Notification

    # Create Dept B actor and an assignee
    # Use pbkdf2 for compatibility in test envs without scrypt support
    actor = User(email="b_actor@example.com", password_hash=generate_password_hash("password123", method="pbkdf2:sha256"), department="B", name="B Actor")
    assignee = User(email="b_assignee@example.com", password_hash=generate_password_hash("password123", method="pbkdf2:sha256"), department="B", name="B Assignee")
    db.session.add_all([actor, assignee])
    db.session.commit()

    # Create a request owned by Dept B and assigned to the assignee
    req = ReqModel(
        title="Test",
        request_type="part_number",
        description="desc",
        priority="low",
        owner_department="B",
        status="B_FINAL_REVIEW",
        assigned_to_user=assignee,
        requires_c_review=False,
        created_by_user_id=actor.id,
        due_at=None,
    )
    # due_at is non-nullable in model, set a value
    from datetime import datetime, timedelta
    req.due_at = datetime.utcnow() + timedelta(days=7)
    db.session.add(req)
    db.session.commit()

    # Login as actor
    rv = client.post("/auth/login", data={"email": actor.email, "password": "password123"}, follow_redirects=True)
    assert rv.status_code == 200

    # Post transition to SENT_TO_A. This is a handoff so include submission_summary
    resp = client.post(f"/requests/{req.id}/transition", data={
        "to_status": "SENT_TO_A",
        "submission_summary": "handoff summary",
        "submission_details": "details",
    }, follow_redirects=True)

    assert resp.status_code == 200

    with app.app_context():
        r = db.session.get(ReqModel, req.id)
        assert r is not None
        assert r.status == "SENT_TO_A"
        # assignment should be cleared
        assert r.assigned_to_user is None

        # assignment_changed audit entry should exist
        ac = AuditLog.query.filter_by(request_id=r.id, action_type="assignment_changed").first()
        assert ac is not None

        # previous assignee should have received a notification about cleared assignment
        n = Notification.query.filter_by(user_id=assignee.id, request_id=r.id, type="assignment_cleared").first()
        assert n is not None
