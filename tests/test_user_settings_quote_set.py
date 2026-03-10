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
    assert b"Message set" in rv.data
    assert b"Rotating quotes enabled" in rv.data

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

    # if we clear the preference, dashboard should fall back to the
    # motivational site default rather than the legacy laundry-heavy set
    rv = client.post(
        "/auth/settings",
        data={"quote_set": ""},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/dashboard")
    assert rv.status_code == 200
    assert b"Progress, not perfection." in rv.data

    # now disable quotes entirely and verify dashboard hides them
    rv = client.post(
        "/auth/settings",
        data={"quotes_enabled": ""},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/dashboard")
    assert b"rolling-quotes-data" not in rv.data
    rv = client.get("/auth/settings")
    assert rv.status_code == 200
    assert b"Rotating quotes disabled" in rv.data


def test_quote_set_normalization_and_case_insensitive(app, client):
    """Ensure user preference is normalized and matched regardless of case.

    This covers the situation where a user record might contain an
    uppercase or otherwise mis‑cased value from a previous release or manual
    edit; the dashboard should still pick the intended set instead of falling
    back to the global/active set (e.g. "laundry riddles").
    """
    with app.app_context():
        # create a user whose quote_set is mixed/caps
        u = User(
            email="case@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
        )
        # assign uppercase value to exercise normalization validator
        u.quote_set = "ENGINEERING"
        db.session.add(u)
        db.session.commit()
        # confirm stored value was normalized
        u2 = User.query.filter_by(email="case@example.com").first()
        assert u2.quote_set == "engineering"

    # login and expect engineering quote on dashboard even though value was
    # originally all-caps
    rv = login(client, email="case@example.com", password="secret")
    assert rv.status_code == 200
    rv = client.get("/dashboard")
    assert rv.status_code == 200
    assert b"First, solve the problem." in rv.data

    # additionally simulate a stray value that doesn't match case in the
    # DB (e.g. someone manually inserted "Engineering"), and verify the
    # lookup logic ignores case when choosing quotes.
    with app.app_context():
        u3 = User.query.filter_by(email="case@example.com").first()
        u3.quote_set = "Engineering"
        db.session.commit()

    rv = client.get("/dashboard")
    assert b"First, solve the problem." in rv.data


def test_external_branding_hides_theme_picker_and_preserves_existing_vibe(app, client):
    with app.app_context():
        user = User(
            email="theme-lock@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
            vibe_index=4,
        )
        db.session.add(user)
        cfg = SiteConfig.get()
        original_logo = cfg.logo_filename
        cfg.logo_filename = "brand/logo.png"
        db.session.commit()

    try:
        rv = login(client, email="theme-lock@example.com", password="secret")
        assert rv.status_code == 200

        settings_page = client.get("/auth/settings")
        assert settings_page.status_code == 200
        assert b"<label for=\"vibe_index\" class=\"form-label\">Theme</label>" not in settings_page.data

        rv = client.post(
            "/auth/settings",
            data={"vibe_index": "9", "quote_set": "engineering"},
            follow_redirects=True,
        )
        assert rv.status_code == 200

        with app.app_context():
            refreshed = User.query.filter_by(email="theme-lock@example.com").first()
            assert refreshed is not None
            assert refreshed.vibe_index == 4
            assert refreshed.quote_set == "engineering"
    finally:
        with app.app_context():
            cfg = SiteConfig.get()
            cfg.logo_filename = original_logo
            db.session.commit()
