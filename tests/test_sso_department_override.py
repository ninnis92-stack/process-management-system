from werkzeug.security import generate_password_hash

from app.auth.sso import oauth
from app.extensions import db
from app.models import FeatureFlags, User


def _login_admin(client, email="admin@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_admin_can_set_department_override(client, app):
    with app.app_context():
        admin = User(
            email="admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        user = User(
            email="sso-user@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            sso_sub="oidc-123",
        )
        db.session.add_all([admin, user])
        db.session.commit()
        user_id = user.id

    rv = _login_admin(client)
    assert rv.status_code == 200

    rv = client.post(
        f"/admin/users/{user_id}/edit",
        data={
            "email": "sso-user@example.com",
            "name": "SSO User",
            "password": "",
            "role": "user",
            "department": "C",
            "department_override": "y",
            "is_active": "y",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.department == "C"
        assert user.department_override is True


def test_sso_callback_updates_primary_department_when_not_overridden(client, app, monkeypatch):
    app.config.update(
        SSO_DEPARTMENT_SYNC_ENABLED=True,
        SSO_DEPARTMENT_CLAIM="profile.department",
        SSO_DEPARTMENT_MAP={"ops": "B"},
    )
    with app.app_context():
        flags = FeatureFlags(sso_department_sync_enabled=True)
        user = User(
            email="sso-sync@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            sso_sub="oidc-sync",
            department_override=False,
        )
        db.session.add_all([flags, user])
        db.session.commit()

    class _FakeOIDC:
        def authorize_access_token(self):
            return {"access_token": "fake"}

        def parse_id_token(self, token):
            return {
                "sub": "oidc-sync",
                "email": "sso-sync@example.com",
                "name": "Sync User",
                "profile": {"department": "ops"},
            }

    monkeypatch.setattr(oauth, "oidc", _FakeOIDC(), raising=False)

    rv = client.get("/auth/sso/callback", follow_redirects=False)
    assert rv.status_code == 302

    with app.app_context():
        user = User.query.filter_by(email="sso-sync@example.com").first()
        assert user.department == "B"


def test_sso_callback_keeps_admin_override_primary_department(client, app, monkeypatch):
    app.config.update(
        SSO_DEPARTMENT_SYNC_ENABLED=True,
        SSO_DEPARTMENT_CLAIM="department",
        SSO_DEPARTMENT_MAP={},
    )
    with app.app_context():
        flags = FeatureFlags(sso_department_sync_enabled=True)
        user = User(
            email="sso-override@example.com",
            password_hash=generate_password_hash("secret"),
            department="C",
            is_active=True,
            sso_sub="oidc-override",
            department_override=True,
        )
        db.session.add_all([flags, user])
        db.session.commit()

    class _FakeOIDC:
        def authorize_access_token(self):
            return {"access_token": "fake"}

        def parse_id_token(self, token):
            return {
                "sub": "oidc-override",
                "email": "sso-override@example.com",
                "name": "Override User",
                "department": "A",
            }

    monkeypatch.setattr(oauth, "oidc", _FakeOIDC(), raising=False)

    rv = client.get("/auth/sso/callback", follow_redirects=False)
    assert rv.status_code == 302

    with app.app_context():
        user = User.query.filter_by(email="sso-override@example.com").first()
        assert user.department == "C"