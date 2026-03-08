import pytest
from app.extensions import db
from app.models import User, SiteConfig
from werkzeug.security import generate_password_hash


def login(client, email="user@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_user_can_select_quote_set(app, client):
    with app.app_context():
        # create normal user
        u = User(
            email="user@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
        )
        db.session.add(u)
        db.session.commit()
        # ensure site config exists so defaults are in place
        cfg = SiteConfig.get()
        db.session.commit()

    rv = login(client)
    assert rv.status_code == 200

    # load settings page and verify quote_set field and toggle present
    rv = client.get("/auth/settings")
    assert rv.status_code == 200
    assert b"Rolling Quote Set" in rv.data
    assert b"Show rotating quotes" in rv.data

    # select the engineering set and save
    rv = client.post(
        "/auth/settings",
        data={"quote_set": "engineering"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Settings saved" in rv.data

    # dashboard should now render a line from engineering set
    rv = client.get("/dashboard")
    assert rv.status_code == 200
    assert b"First, solve the problem." in rv.data

    # if we clear the preference, dashboard should fall back to default quotes
    rv = client.post(
        "/auth/settings",
        data={"quote_set": ""},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/dashboard")
    assert rv.status_code == 200
    # default set includes "Sort today" phrase
    assert b"Sort today: socks first" in rv.data

    # now disable quotes entirely and verify dashboard hides them
    rv = client.post(
        "/auth/settings",
        data={"quotes_enabled": ""},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/dashboard")
    assert b"rolling-quotes-data" not in rv.data
