from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import FeatureFlags, Notification, Request as ReqModel, User


def test_user_push_nudge_obeys_feature_flag(app, client):
    actor = User(
        email="actor@example.com",
        password_hash=generate_password_hash("password123", method="pbkdf2:sha256"),
        department="B",
        name="Actor",
        is_active=True,
    )
    owner = User(
        email="owner@example.com",
        password_hash=generate_password_hash("password123", method="pbkdf2:sha256"),
        department="B",
        name="Owner",
        is_active=True,
    )
    db.session.add_all([actor, owner])
    db.session.commit()

    req = ReqModel(
        title="Reminder test",
        request_type="part_number",
        description="Testing user reminders",
        priority="medium",
        owner_department="B",
        status="B_IN_PROGRESS",
        assigned_to_user=owner,
        created_by_user_id=actor.id,
    )
    req.due_at = datetime.utcnow() + timedelta(days=7)
    db.session.add(req)
    db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": actor.email, "password": "password123"},
        follow_redirects=True,
    )
    assert rv.status_code == 200

    resp = client.post(f"/requests/{req.id}/push_reminder", follow_redirects=False)
    assert resp.status_code == 403

    with app.app_context():
        flags = FeatureFlags.get()
        flags.allow_user_nudges = True
        db.session.commit()

    resp = client.post(f"/requests/{req.id}/push_reminder", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        note = (
            Notification.query.filter_by(
                user_id=owner.id, request_id=req.id, type="nudge"
            )
            .order_by(Notification.created_at.desc())
            .first()
        )
        assert note is not None
        assert note.dedupe_key == f"user_nudge:req_{req.id}"