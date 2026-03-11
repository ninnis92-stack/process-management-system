from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import User, Request as ReqModel, WebhookSubscription, FormTemplate, FormField, IntegrationConfig
from datetime import datetime, timedelta
from app.services.integrations import get_integration_scaffold, normalize_integration_config


def test_requests_api_and_webhook_subscription(client, app):
    import importlib
    import api.index as api_index

    api_index = importlib.reload(api_index)
    api_app = api_index.app

    with api_app.app_context():
        db.create_all()
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

    # the versioned API is mounted at /api/v1; older unversioned
    # endpoints are redirected by the catch-all handler shown above.
    rv = api.get("/api/v1/requests", headers=headers)
    assert rv.status_code == 200
    assert b"Exportable Request" in rv.data

    # ensure template listings include layout field and validate schema
    from app.api.v1.schemas import TemplateSchema

    rv2 = api.get("/api/v1/templates", headers=headers)
    assert rv2.status_code == 200
    data = rv2.get_json()
    assert data.get("ok") is True
    if data.get("templates"):
        assert "layout" in data["templates"][0]
        # run marshmallow sanity check
        TemplateSchema(many=True).load(data["templates"])

    rv = api.post(
        "/api/v1/integrations/webhook-subscriptions",
        json={"url": "https://example.com/hook", "events": ["request.status_changed"]},
        headers=headers,
    )
    assert rv.status_code == 201

    with api_app.app_context():
        sub = WebhookSubscription.query.filter_by(url="https://example.com/hook").first()
        assert sub is not None
        assert sub.events == ["request.status_changed"]

    rv = api.post(
        "/api/v1/integrations/fetch",
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


def test_versioned_openapi_document(client, app):
    import importlib
    import api.index as api_index

    api_index = importlib.reload(api_index)
    api = api_index.app.test_client()

    rv = api.get("/api/v1/openapi.json")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["openapi"] == "3.0.3"
    assert "/templates" in data["paths"]
    assert "/requests" in data["paths"]


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


def test_api_template_verify_uses_tracker_integration(client, app, monkeypatch):
    import importlib
    import api.index as api_index

    api_index = importlib.reload(api_index)
    api_app = api_index.app

    class DummyHTTPResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self.text = str(payload)

        def json(self):
            return self._payload

    with api_app.app_context():
        admin = User(
            email="verify-api-admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

        template = FormTemplate(name="API Verify Template", description="Template verify")
        db.session.add(template)
        db.session.commit()
        template_id = template.id

        field = FormField(
            template_id=template.id,
            name="badge_id",
            label="Badge ID",
            field_type="text",
            required=True,
            verification={"provider": "verification", "external_key": "badge_id", "params": {"department": "A"}},
        )
        db.session.add(field)

        cfg = IntegrationConfig(
            department="A",
            kind="verification",
            enabled=True,
            config='{"trackers": {"default": {"endpoints": {"base_url": "https://directory.example.com", "validate": "/check"}, "request": {"method": "GET", "payload_location": "query", "query_template": {"badge": "{value}"}}, "response": {"ok_path": "ok", "detail_path": "details"}}}}',
        )
        db.session.add(cfg)
        db.session.commit()

    monkeypatch.setattr(
        "requests.sessions.Session.request",
        lambda self, method, url, **kwargs: DummyHTTPResponse({"ok": True, "details": {"badge": kwargs.get("params", {}).get("badge")}}),
    )

    api = api_app.test_client()
    headers = {"X-Api-Key": "test-key"}
    rv = api.post(
        f"/api/templates/{template_id}/verify",
        json={"badge_id": "B-100"},
        headers=headers,
    )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["results"]["badge_id"]["ok"] is True
    assert body["results"]["badge_id"]["details"]["badge"] == "B-100"
    # verify layout key is returned (default standard)
    assert body.get("layout") == "standard"


def test_api_template_external_schema_exposes_layout_and_sections(client, app):
    import importlib
    import api.index as api_index

    api_index = importlib.reload(api_index)
    api_app = api_index.app

    with api_app.app_context():
        db.create_all()
        template = FormTemplate(
            name="External Schema Template",
            description="Schema export",
            layout="compact",
            external_enabled=True,
            external_provider="microsoft_forms",
            external_form_id="schema-1",
        )
        db.session.add(template)
        db.session.commit()
        db.session.add(
            FormField(
                template_id=template.id,
                name="request_reason",
                label="Request reason",
                section_name="Details",
                field_type="textarea",
                required=True,
            )
        )
        db.session.commit()
        template_id = template.id

    api = api_app.test_client()
    headers = {"X-Api-Key": "test-key"}
    rv = api.get(f"/api/templates/{template_id}/external-schema", headers=headers)
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True
    assert body["template"]["layout"] == "compact"
    assert body["template"]["fields"][0]["name"] == "request_reason"
    assert body["template"]["sections"][0]["name"] == "Details"
