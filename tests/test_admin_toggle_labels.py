import pytest
from app.extensions import db
from app.models import FeatureFlags, RejectRequestConfig, User
from werkzeug.security import generate_password_hash


def login_admin(client, email="admin@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


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


def test_feature_flags_render_correct_action_labels(client, app):
    """Labels on the feature‑flags page should describe the current state.

    Checked switches now read as enabled and unchecked switches read as
    disabled so the UI matches what an admin is actually seeing.
    """

    make_admin(app)
    with app.app_context():
        flags = FeatureFlags.get()
        flags.enable_notifications = True
        flags.enable_nudges = False
        flags.vibe_enabled = True
        db.session.commit()

    rv = login_admin(client)
    assert rv.status_code == 200

    rv = client.get("/admin/feature_flags")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)

    assert 'data-toggle-text-checked="Notifications enabled"' in html
    assert 'Notifications enabled' in html
    assert 'Automated reminders disabled' in html
    assert 'Vibe button UI enabled' in html
    assert 'surface-panel admin-feature-flags-panel' in html
    assert 'admin-feature-flags__section' in html
    assert 'admin-toggle-card admin-feature-flags__option' in html

    # simulate saving new values and verify the returned page reflects them
    rv2 = client.post(
        "/admin/feature_flags",
        data={
            "enable_notifications": "y",
            "enable_nudges": "y",
            "allow_user_nudges": "",
            "vibe_enabled": "y",
            "sso_admin_sync_enabled": "y",
            "sso_department_sync_enabled": "",
            "enable_external_forms": "",
            "rolling_quotes_enabled": "y",
        },
        follow_redirects=True,
    )
    assert rv2.status_code == 200
    html2 = rv2.get_data(as_text=True)
    assert 'Automated reminders enabled' in html2


def test_admin_dashboard_uses_shared_action_shells(client, app):
    make_admin(app)
    rv = login_admin(client)
    assert rv.status_code == 200

    rv = client.get("/admin/")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)

    assert 'admin-hero__actions ui-action-bar' in html
    assert 'ui-action-group' in html
    assert 'ui-action-note' in html
    assert 'data-vibe-shell' in html


def test_feature_flags_post_unchecked_boxes_disable_flags(client, app):
    make_admin(app)
    with app.app_context():
        flags = FeatureFlags.get()
        flags.enable_notifications = True
        flags.enable_nudges = True
        flags.allow_user_nudges = True
        db.session.commit()

    rv = login_admin(client)
    assert rv.status_code == 200

    rv = client.post(
        "/admin/feature_flags",
        data={},
        follow_redirects=True,
    )
    assert rv.status_code == 200

    with app.app_context():
        flags = FeatureFlags.get()
        assert flags.enable_notifications is False
        assert flags.enable_nudges is False
        assert flags.allow_user_nudges is False


def test_feature_flags_autosave_support(client, app):
    """Page should include autosave endpoint attribute and unload script."""
    make_admin(app)
    rv = login_admin(client)
    assert rv.status_code == 200
    rv = client.get("/admin/feature_flags")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert 'data-autosave-endpoint="/admin/feature_flags"' in html
    # verify global JS includes beforeunload handler to flush autosaves
    # and the new fetch+keepalive logic (not sendBeacon) so JSON posts work
    # root redirects logged-in users so hit dashboard directly
    base = client.get("/dashboard")
    assert b"beforeunload" in base.data
    assert b"keepalive" in base.data
    assert b"form:autosaved" in base.data


def test_feature_flags_json_autosave_updates(client, app):
    """POSTing JSON should update flags without redirect and return state."""
    make_admin(app)
    with app.app_context():
        flags = FeatureFlags.get()
        flags.vibe_enabled = False
        db.session.commit()

    rv = login_admin(client)
    assert rv.status_code == 200
    rv = client.post(
        "/admin/feature_flags",
        json={"vibe_enabled": True, "enable_nudges": False},
    )
    assert rv.status_code == 200
    payload = rv.get_json()
    assert payload["ok"] is True
    assert payload["flags"]["vibe_enabled"] is True
    assert payload["flags"]["enable_nudges"] is False
    with app.app_context():
        flags = FeatureFlags.get()
        assert flags.vibe_enabled is True
        assert flags.enable_nudges is False


def test_feature_flags_fallback_defaults_keep_vibe_enabled(app, monkeypatch):
    with app.app_context():
        class _ExecuteResult:
            def fetchone(self):
                return (1,)

        def fake_execute(*args, **kwargs):
            return _ExecuteResult()

        def fake_get(*args, **kwargs):
            raise RuntimeError("schema drift")

        monkeypatch.setattr(db.session, "execute", fake_execute)
        monkeypatch.setattr(db.session, "get", fake_get)

        flags = FeatureFlags.get()

        assert flags.vibe_enabled is True
        assert flags.enable_notifications is True
        assert flags.enable_nudges is True


def test_reject_request_config_label_describes_state(client, app):
    make_admin(app)
    with app.app_context():
        cfg = RejectRequestConfig.get()
        cfg.enabled = False
        db.session.commit()

    rv = login_admin(client)
    assert rv.status_code == 200
    rv = client.get("/admin/reject_request_config")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert 'Reject request disabled' in html
    # the checkbox should also expose the on/off texts as attributes
    assert 'data-toggle-text-checked="Reject request enabled"' in html
def test_dashboard_notification_toggle(client, app):
    """Verify dashboard toggle tile label updates with flag state and posts correctly."""
    make_admin(app)
    with app.app_context():
        flags = FeatureFlags.get()
        flags.enable_notifications = False
        db.session.commit()

    rv = login_admin(client)
    assert rv.status_code == 200

    rv = client.get("/admin/")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Notifications off" in html

    rv = client.post("/admin/toggle_notifications", follow_redirects=True)
    assert rv.status_code == 200
    with app.app_context():
        assert FeatureFlags.get().enable_notifications is True
    html = rv.get_data(as_text=True)
    assert "Notifications on" in html
    # active class should be applied when flag is enabled
    assert 'admin-toggle-card active' in html
