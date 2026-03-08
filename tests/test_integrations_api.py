from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import User, Request as ReqModel, WebhookSubscription
from datetime import datetime, timedelta
from app.services.integrations import get_integration_scaffold, normalize_integration_config


def test_requests_api_and_webhook_subscription(client, app):
    from api.index import app as api_app

    with api_app.app_context():
        admin = User(
            email="api-admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

        req = ReqModel(
            title="Exportable Request",
            request_type="both",
            pricebook_status="unknown",
            description="x",
            priority="medium",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        db.session.add(req)
        db.session.commit()

    api = api_app.test_client()
    headers = {"X-Api-Key": "test-key"}

    rv = api.get("/api/requests", headers=headers)
    assert rv.status_code == 200
    assert b"Exportable Request" in rv.data

    rv = api.post(
        "/api/integrations/webhook-subscriptions",
        json={"url": "https://example.com/hook", "events": ["request.status_changed"]},
        headers=headers,
    )
    assert rv.status_code == 201

    with api_app.app_context():
        sub = WebhookSubscription.query.filter_by(url="https://example.com/hook").first()
        assert sub is not None
        assert sub.events == ["request.status_changed"]

    rv = api.post(
        "/api/integrations/fetch",
        json={"provider": "echo", "config": {"source": "demo"}, "query": {"q": "abc"}},
        headers=headers,
    )
    assert rv.status_code == 200
    assert b'"provider":"echo"' in rv.data


def test_integration_scaffold_normalization_defaults():
    scaffold = get_integration_scaffold("webhook")
    assert scaffold["default_config"]["provider"] == "generic_webhook"

    normalized = normalize_integration_config(
        "webhook",
        '{"provider": "custom_partner", "endpoints": {"url": "https://example.com/hook"}}',
    )
    assert normalized["kind"] == "webhook"
    assert normalized["provider"] == "custom_partner"
    assert normalized["version"] == "2026-03"
    assert normalized["endpoints"]["url"] == "https://example.com/hook"
    assert normalized["compatibility"]["signature_header"] == "X-Webhook-Signature"


def test_admin_integration_edit_shows_scaffold(client, app):
    with app.app_context():
        admin = User(
            email="integration-admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "integration-admin@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    rv = client.get("/admin/integrations/new")
    assert rv.status_code == 200
    assert b"Load starter scaffold" in rv.data
    assert b"generic_ticketing" in rv.data or b"generic_webhook" in rv.data
