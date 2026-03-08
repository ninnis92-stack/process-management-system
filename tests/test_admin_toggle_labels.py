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
    """Labels on the feature‑flags page should describe the *action*.

    The macros we added generate either "Enable …" or "Disable …" based on
    the current stored value.
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

    # notification toggle should show "Disable" when enabled
    # ensure the macro added data attributes so JS could update the label
    assert 'data-toggle-text-on="Disable notifications"' in html
    assert 'Disable notifications' in html
    # nudge toggle should show "Enable" when disabled
    assert 'Enable nudges' in html
    # vibe toggle text derived from label above
    assert 'Disable Vibe button UI' in html


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
    assert 'Enable reject request' in html
    # the checkbox should also expose the on/off texts as attributes
    assert 'data-toggle-text-on="Disable reject request"' in html
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
