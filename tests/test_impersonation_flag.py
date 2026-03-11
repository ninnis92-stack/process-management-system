import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import User

# reuse helpers similar to other tests


def make_admin(app):
    with app.app_context():
        u = User.query.filter_by(email="admin@example.com").first()
        if not u:
            u = User(
                email="admin@example.com",
                password_hash=generate_password_hash("secret"),
                department="B",
                is_active=True,
                is_admin=True,
            )
            db.session.add(u)
            db.session.commit()
        else:
            u.is_admin = True
            db.session.commit()
        return u


def login_admin(client, email="admin@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_impersonation_routes_disabled_by_default(client, app):
    make_admin(app)
    rv = login_admin(client)
    assert rv.status_code == 200

    # flag should default to False
    assert not app.config.get("ALLOW_IMPERSONATION")

    # the users page should not offer an impersonation button
    rv = client.get("/admin/users")
    assert b"Act as Dept" not in rv.data

    # if somebody somehow has the session keys, none of the "stop" UI should
    # render when the feature is disabled
    with client.session_transaction() as sess:
        sess["impersonate_admin_id"] = 1
        sess["impersonate_dept"] = "A"
    rv = client.get("/admin/users")
    assert b"Stop Impersonation" not in rv.data
    # clear the manually injected keys before exercising the POST route, so it
    # can't accidentally succeed due to them
    with client.session_transaction() as sess:
        sess.pop("impersonate_admin_id", None)
        sess.pop("impersonate_dept", None)

    rv = client.post(
        "/admin/impersonate/dept",
        data={"dept": "A"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Impersonation feature is disabled" in rv.data
    with client.session_transaction() as sess:
        assert "impersonate_dept" not in sess

    # stopping should also just redirect harmlessly (route is under /admin)
    rv = client.get("/admin/impersonate/stop", follow_redirects=True)
    assert b"Impersonation feature is disabled" in rv.data


def test_impersonation_can_be_enabled_and_works(client, app):
    app.config["ALLOW_IMPERSONATION"] = True
    make_admin(app)
    # create a second non-admin user so the table has someone to impersonate
    with app.app_context():
        if not User.query.filter_by(email="user@example.com").first():
            u2 = User(
                email="user@example.com",
                password_hash=generate_password_hash("pw"),
                department="A",
                is_active=True,
            )
            db.session.add(u2)
            db.session.commit()

    rv = login_admin(client)
    assert rv.status_code == 200

    # flag enabled, users page should show the button for the other user
    rv = client.get("/admin/users")
    assert b"Act as Dept" in rv.data

    rv = client.post(
        "/admin/impersonate/dept",
        data={"dept": "A"},
        follow_redirects=True,
    )
    assert b"Now acting as a member of Dept A" in rv.data
    with client.session_transaction() as sess:
        assert sess.get("impersonate_dept") == "A"

    # stopping should clear session (route under /admin)
    rv = client.get("/admin/impersonate/stop", follow_redirects=True)
    assert b"Stopped acting-as" in rv.data
    with client.session_transaction() as sess:
        assert "impersonate_dept" not in sess
