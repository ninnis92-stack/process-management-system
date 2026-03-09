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


def test_settings_page_shows_disable_text_when_dark_mode_enabled(client, app):
    make_user(app, dark_mode=True)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.get("/auth/settings")
    assert rv.status_code == 200
    # the dark mode label should reflect the preference
    assert b'id="darkModeLabel">Dark mode enabled<' in rv.data
    assert b"Changes save automatically." in rv.data
    assert b'id="darkModeSubmitBtn"' not in rv.data
    # the checkbox input should be checked so the client script can
    # initialize body class correctly
    assert b'<input checked' in rv.data.split(b'name="dark_mode"')[0]
    # body tag should already include the dark-mode class server-side
    m = re.search(rb"<body[^>]*class=[\'\"]([^\'\"]*)[\'\"]", rv.data)
    assert m, "no body tag?"
    assert b"dark-mode" in m.group(1)
    # ensure the client-side preview script is present
    assert b"document.body.classList.toggle('dark-mode', checkbox.checked)" in rv.data
    assert b"/auth/preferences" in rv.data


def test_settings_page_shows_enable_text_when_dark_mode_disabled(client, app):
    make_user(app, dark_mode=False)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.get("/auth/settings")
    assert rv.status_code == 200
    assert b'id="darkModeLabel">Dark mode disabled<' in rv.data
    assert b"Changes save automatically." in rv.data
    assert b'id="darkModeSubmitBtn"' not in rv.data


def test_generic_preferences_endpoint_updates_multiple_settings(client, app):
    make_user(app, dark_mode=False)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.post(
        "/auth/preferences",
        json={
            "dark_mode": True,
            "quotes_enabled": False,
            "quote_set": "engineering",
            "quote_interval": 30,
            "vibe_index": 5,
        },
    )
    assert rv.status_code == 200
    payload = rv.get_json()
    assert payload["ok"] is True
    assert payload["preferences"]["dark_mode"] is True
    assert payload["preferences"]["quotes_enabled"] is False
    assert payload["preferences"]["quote_set"] == "engineering"
    assert payload["preferences"]["quote_interval"] == 30
    assert payload["preferences"]["vibe_index"] == 5

    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        assert user is not None
        assert user.dark_mode is True
        assert user.quotes_enabled is False
        assert user.quote_set == "engineering"
        assert user.quote_interval == 30


def test_vibe_endpoint_persists_and_settings_reflect(client, app):
    """Sending a vibe index should update the user and show up in settings."""
    make_user(app, dark_mode=False)
    rv = login(client)
    assert rv.status_code == 200

    # choose a non-zero vibe
    rv = client.post(
        "/auth/vibe",
        json={"vibe_index": 5},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data.get("ok") is True
    # endpoint doesn't echo the index back; state is persisted server-side

    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        assert user.vibe_index == 5

    # now load the settings page and confirm the dropdown reflects it
    rv = client.get("/auth/settings")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    # the option for value 5 should be marked selected
    assert 'value="5" selected' in html


def test_settings_post_unchecked_dark_mode_disables_preference(client, app):
    make_user(app, dark_mode=True)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.post(
        "/auth/settings",
        data={
            "dark_mode_present": "1",
            "quotes_enabled_present": "1",
            "quotes_enabled": "y",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200

    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        assert user is not None
        assert user.dark_mode is False


def test_settings_post_checked_dark_mode_enables_preference(client, app):
    make_user(app, dark_mode=False)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.post(
        "/auth/settings",
        data={
            "dark_mode_present": "1",
            "dark_mode": "y",
            "quotes_enabled_present": "1",
            "quotes_enabled": "y",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200

    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        assert user is not None
        assert user.dark_mode is True


def test_dark_mode_preference_endpoint_enables_account_wide_setting(client, app):
    make_user(app, dark_mode=False)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.post(
        "/auth/preferences/dark-mode",
        json={"dark_mode": True},
    )
    assert rv.status_code == 200
    assert rv.get_json()["ok"] is True
    assert rv.get_json()["dark_mode"] is True

    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        assert user is not None
        assert user.dark_mode is True

    rv = client.get("/dashboard")
    assert rv.status_code == 200
    m = re.search(rb"<body[^>]*class=[\'\"]([^\'\"]*)[\'\"]", rv.data)
    assert m, "no body tag?"
    assert b"dark-mode" in m.group(1)


def test_dark_mode_preference_endpoint_disables_account_wide_setting(client, app):
    make_user(app, dark_mode=True)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.post(
        "/auth/preferences/dark-mode",
        json={"dark_mode": False},
    )
    assert rv.status_code == 200
    assert rv.get_json()["ok"] is True
    assert rv.get_json()["dark_mode"] is False

    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        assert user is not None
        assert user.dark_mode is False

    rv = client.get("/dashboard")
    assert rv.status_code == 200
    m = re.search(rb"<body[^>]*class=[\'\"]([^\'\"]*)[\'\"]", rv.data)
    assert m, "no body tag?"
    assert b"dark-mode" not in m.group(1)
