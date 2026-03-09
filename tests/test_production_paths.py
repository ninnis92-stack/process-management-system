import json

from app.auth.sso import oauth
from app.security import compute_webhook_signature


def test_sso_login_falls_back_to_local_login_when_disabled(client, app):
    app.config["SSO_ENABLED"] = False

    response = client.get("/auth/sso/login", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")


def test_sso_callback_returns_400_without_email_claim(client, app, monkeypatch):
    app.config["SSO_ENABLED"] = True

    class _FakeOIDC:
        def authorize_access_token(self):
            return {"access_token": "fake"}

        def parse_id_token(self, token):
            return {"sub": "oidc-user", "name": "No Email User"}

    monkeypatch.setattr(oauth, "oidc", _FakeOIDC(), raising=False)

    response = client.get("/auth/sso/callback", follow_redirects=False)

    assert response.status_code == 400
    assert b"no email claim" in response.data.lower()


def test_login_page_makes_sso_option_clear_when_enabled(client, app):
    app.config["SSO_ENABLED"] = True

    response = client.get("/auth/login")

    assert response.status_code == 200
    assert b"Continue with SSO" in response.data
    assert b"Or use local credentials" in response.data
    assert b"Use email and password only if an administrator gave you local credentials" in response.data


def test_timestamped_webhook_replay_is_rejected(app, client, monkeypatch):
    app.config["WEBHOOK_SHARED_SECRET"] = "secret-123"
    app.config["WEBHOOK_REQUIRE_TIMESTAMP"] = True
    app.config["WEBHOOK_REPLAY_PROTECTION_ENABLED"] = True
    payload = {"hello": "world"}
    raw = json.dumps(payload).encode("utf-8")
    timestamp = "1893456600"
    sig = compute_webhook_signature(
        app.config["WEBHOOK_SHARED_SECRET"], raw, timestamp=timestamp
    )

    monkeypatch.setattr("app.security.time.time", lambda: 1893456600)

    first = client.post(
        "/integrations/incoming-webhook",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": sig,
        },
    )
    second = client.post(
        "/integrations/incoming-webhook",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": sig,
        },
    )

    assert first.status_code == 204
    assert second.status_code == 401


def test_inbound_mail_requires_valid_signature(client, app):
    app.config["WEBHOOK_SHARED_SECRET"] = "secret-123"

    response = client.post(
        "/integrations/inbound-mail",
        data=json.dumps({"from": "user@example.com", "subject": "hello"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Webhook-Signature": "bad"},
    )

    assert response.status_code == 401