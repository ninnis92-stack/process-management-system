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
    m = re.search(rb"<body[^>]*class=[\'\"]([^\'\"]*)[\'\"]", rv.data)
    assert m, "no body tag?"
    assert b"dark-mode" in m.group(1)


def test_admin_dashboard_keeps_dark_mode_and_hides_vibe_controls(client, app):
    make_user(app, dark_mode=True)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.get("/admin/")
    assert rv.status_code == 200
    m = re.search(rb"<body[^>]*class=[\'\"]([^\'\"]*)[\'\"]", rv.data)
    assert m, "no body tag?"
    assert b"dark-mode" in m.group(1)
    # vibe buttons should not be rendered when dark mode is active
    assert b'id="vibeBtn"' not in rv.data
    assert b'id="vibeBtnAdmin"' not in rv.data


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


def test_dashboard_shows_navbar_vibe_button_in_brand_banner(client, app):
    make_user(app, dark_mode=False)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.get("/dashboard")
    assert rv.status_code == 200
    cluster = rv.data.split(b'class="brand-cluster"', 1)[1].split(b'<button class="navbar-toggler"', 1)[0]
    assert b'class="brand-banner-row"' in rv.data
    assert b'class="brand-banner-row__quote-panel"' in rv.data
    assert b'class="brand-banner-row__control-panel"' in rv.data
    assert b'brand-banner-row__control-shell' in rv.data
    assert b'data-vibe-shell' in rv.data
    assert b'data-theme-banner' in rv.data
    assert b'id="motivation"' in rv.data
    assert b'id="vibeBtn"' in rv.data
    assert rv.data.index(b'id="motivation"') < rv.data.index(b'id="vibeBtn"')
    assert cluster.index(b'</a>') < cluster.index(b'id="vibeBtn"')
    assert b'Current vibe' in rv.data

    # new CSS rules should make brand-stack sit above the banner and add spacing
    with open('app/static/styles.css', 'r') as f:
        css = f.read()
    assert '.brand-stack' in css and 'z-index: 2' in css
    assert '.brand-banner-row' in css and 'margin-left: 0.5rem' in css
    assert '.brand-banner-row__control-shell' in css
    assert '.ui-control-shell--banner' in css
    assert 'background: rgb(var(--accent-rgb, 79, 140, 255));' in css


def test_dashboard_brand_banner_renders_without_vibe_button_when_feature_disabled(client, app):
    make_user(app, dark_mode=False)
    with app.app_context():
        from app.models import FeatureFlags

        flags = FeatureFlags.get()
        flags.vibe_enabled = False
        db.session.commit()

    rv = login(client)
    assert rv.status_code == 200
    rv = client.get("/dashboard")
    assert rv.status_code == 200
    assert b'class="brand-banner-row brand-banner-row--quotes-only"' in rv.data
    assert b'data-vibe-quote-panel' in rv.data
    assert b'id="motivation"' in rv.data
    assert b'id="vibeBtn"' not in rv.data
    assert b'data-vibe-control-panel' not in rv.data


def test_settings_page_shows_disable_text_when_dark_mode_enabled(client, app):
    make_user(app, dark_mode=True)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.get("/auth/settings")
    assert rv.status_code == 200
    # the dark mode label should reflect the preference
    assert b'id="darkModeLabel">Dark mode enabled<' in rv.data
    assert b'Dark mode disables custom themes; vibe controls are inactive.' in rv.data
    assert b'id="vibeDarkModeNote"' in rv.data
    assert b'id="vibe_index" name="vibe_index" disabled' in rv.data
    assert b'Theme selection is disabled while dark mode is active.' in rv.data
    assert b'data-vibe-preview-badge' not in rv.data
    assert b'data-vibe-compatible-chip=' not in rv.data
    assert b"Changes save automatically." in rv.data
    assert b'id="darkModeSubmitBtn"' not in rv.data
    # the checkbox input should be checked so the client script can
    # initialize body class correctly
    assert b'<input checked' in rv.data.split(b'name="dark_mode"')[0]
    m = re.search(rb"<body[^>]*class=[\'\"]([^\'\"]*)[\'\"]", rv.data)
    assert m, "no body tag?"
    assert b"dark-mode" in m.group(1)
    assert b"document.body.classList.toggle('dark-mode', checkbox.checked)" in rv.data
    assert b"/auth/preferences" in rv.data
    assert b'id="userThemePreview"' in rv.data


def test_settings_page_shows_enable_text_when_dark_mode_disabled(client, app):
    make_user(app, dark_mode=False)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.get("/auth/settings")
    assert rv.status_code == 200
    assert b'id="darkModeLabel">Dark mode disabled<' in rv.data
    assert b'data-all-choices=' in rv.data
    assert b"Changes save automatically." in rv.data
    assert b'id="darkModeSubmitBtn"' not in rv.data


def test_generic_preferences_endpoint_updates_multiple_settings(client, app):
    make_user(app, dark_mode=False)
    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        user.vibe_index = 2
        db.session.commit()
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
    # vibe index should be cleared when dark mode is active
    assert payload["preferences"]["vibe_index"] is None
    rv = client.get("/dashboard")
    m = re.search(rb"<body[^>]*class=[\'\"]([^\'\"]*)[\'\"]", rv.data)
    assert m and b"dark-mode" in m.group(1)

    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        assert user is not None
        assert user.dark_mode is True
        assert user.vibe_index is None
        assert user.quotes_enabled is False
        assert user.quote_set == "engineering"
        assert user.quote_interval == 30


def test_vibe_endpoint_rejects_updates_while_dark_mode_enabled(client, app):
    make_user(app, dark_mode=True)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.post(
        "/auth/vibe",
        json={"vibe_index": 1},
    )
    assert rv.status_code == 409
    payload = rv.get_json()
    assert payload["ok"] is False
    assert payload["error"] == "dark_mode_vibe_disabled"


def test_vibe_endpoint_rejects_any_updates_when_dark_mode_enabled(client, app):
    make_user(app, dark_mode=True)
    rv = login(client)
    assert rv.status_code == 200

    rv = client.post(
        "/auth/vibe",
        json={"vibe_index": 5},
    )
    assert rv.status_code == 409
    payload = rv.get_json()
    assert payload["ok"] is False
    assert payload["error"] == "dark_mode_vibe_disabled"


def test_dark_mode_dashboard_bootstraps_selected_vibe(client, app):
    make_user(app, dark_mode=True)
    with app.app_context():
        user = User.query.filter_by(email="admin@example.com").first()
        user.vibe_index = 5
        db.session.commit()

    rv = login(client)
    assert rv.status_code == 200

    rv = client.get("/dashboard")
    assert rv.status_code == 200
    assert b'data-user-dark-mode="1"' in rv.data
    assert b'data-user-vibe="5"' in rv.data
    # the navbar no longer renders a vibe button when dark mode is active
    assert b'id="vibeBtn"' not in rv.data


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
        # enabling dark mode should clear any existing vibe index
        assert user.vibe_index is None


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
