from datetime import datetime

from app.extensions import db
from app.models import Notification, User
from werkzeug.security import generate_password_hash


def test_notifications_page_lists_items(app, client):
    with app.app_context():
        # create a user
        u = User(email="notify@example.com", password_hash=generate_password_hash("secret"), department="A", is_active=True)
        db.session.add(u)
        db.session.commit()
        # add notifications
        n1 = Notification(user_id=u.id, type="generic", title="Hello", body="First note", created_at=datetime.utcnow())
        n2 = Notification(user_id=u.id, type="generic", title="Second", body="", created_at=datetime.utcnow())
        db.session.add_all([n1, n2])
        db.session.commit()
        uid = u.id
    # login
    rv = client.post("/auth/login", data={"email": "notify@example.com", "password": "secret"})
    assert rv.status_code == 302
    rv = client.get("/notifications/view")
    assert rv.status_code == 200
    assert b"Hello" in rv.data
    assert b"Second" in rv.data
    # mark all read via JS endpoint
    rv = client.post("/notifications/mark_all_read")
    assert rv.get_json().get("ok")
    with app.app_context():
        assert Notification.query.filter_by(user_id=uid, is_read=False).count() == 0


def test_notifications_page_empty(app, client):
    with app.app_context():
        u = User(email="empty@example.com", password_hash=generate_password_hash("secret"), department="A", is_active=True)
        db.session.add(u)
        db.session.commit()
    rv = client.post("/auth/login", data={"email": "empty@example.com", "password": "secret"})
    assert rv.status_code == 302
    rv = client.get("/notifications/view")
    assert rv.status_code == 200
    assert b"No notifications to display" in rv.data
