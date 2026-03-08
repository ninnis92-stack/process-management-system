import re
import pytest
from app.extensions import db
from app.models import User
from werkzeug.security import generate_password_hash


def login(client, email="admin@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def make_user(app, dark_mode=False):
    with app.app_context():
        u = User.query.filter_by(email="admin@example.com").first()
        if not u:
            u = User(
                email="admin@example.com",
                password_hash=generate_password_hash("secret"),
                department="B",
                is_active=True,
                is_admin=True,
                dark_mode=dark_mode,
            )
            db.session.add(u)
        else:
            u.dark_mode = dark_mode
        db.session.commit()
        return u


def test_dark_mode_class_added_server_side(client, app):
    # ensure a user with dark_mode enabled
    make_user(app, dark_mode=True)
    rv = login(client)
    assert rv.status_code == 200

    # request a page and verify the body has the class
    rv = client.get("/dashboard")
    assert rv.status_code == 200
    # body class attribute should include dark-mode
    m = re.search(rb"<body[^>]*class=[\'\"]([^\'\"]*)[\'\"]", rv.data)
    assert m, "no body tag?"
    assert b"dark-mode" in m.group(1)


def test_dark_mode_not_added_by_default(client, app):
    make_user(app, dark_mode=False)
    rv = login(client)
    assert rv.status_code == 200
    rv = client.get("/dashboard")
    assert rv.status_code == 200
    # ensure body class does not include dark-mode
    m = re.search(rb"<body[^>]*class=[\'\"]([^\'\"]*)[\'\"]", rv.data)
    assert m, "no body tag?"
    assert b"dark-mode" not in m.group(1)
