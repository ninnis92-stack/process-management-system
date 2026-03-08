from werkzeug.security import generate_password_hash
from unittest.mock import Mock
import logging
import json

from app.security import compute_webhook_signature
from app.extensions import db
from app.models import User
from app.services.field_verification import apply_bulk_verification_params


def test_request_id_header_is_emitted(app, client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")
    payload = response.get_json()
    assert payload["request_id"] == response.headers.get("X-Request-ID")


def test_request_id_header_is_preserved_from_incoming_request(app, client):
    response = client.get("/health", headers={"X-Request-ID": "req-12345"})

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "req-12345"


def test_ready_endpoint_checks_database_and_emits_request_id(app, client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")
    payload = response.get_json()
    assert payload["request_id"] == response.headers.get("X-Request-ID")
    assert payload["components"]["database"]["status"] == "ok"


def test_ready_endpoint_returns_503_when_database_is_unavailable(app, client, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(db.session, "execute", _boom)

    response = client.get("/ready")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["status"] == "unhealthy"
    assert "database" in payload["failed_checks"]
    assert payload["components"]["database"]["status"] == "unhealthy"


def test_ready_endpoint_can_require_redis(app, client, monkeypatch):
    app.config["HEALTHCHECK_REDIS_REQUIRED"] = True
    app.config["REDIS_URL"] = "redis://example.invalid:6379/0"

    import app.extensions as extensions_module

    fake_redis = Mock()
    fake_redis.ping.side_effect = RuntimeError("redis unavailable")
    monkeypatch.setattr(extensions_module, "redis_client", fake_redis)

    response = client.get("/ready")

    assert response.status_code == 503
    payload = response.get_json()
    assert "redis" in payload["failed_checks"]
    assert payload["components"]["redis"]["required"] is True


def test_request_logging_includes_request_id_and_path(app, client, caplog):
    app.config["REQUEST_LOGGING_ENABLED"] = True

    with caplog.at_level(logging.INFO):
        response = client.get("/health", headers={"X-Request-ID": "req-log-1"})

    assert response.status_code == 200
    messages = [record for record in caplog.records if record.getMessage() == "request completed"]
    assert messages
    record = messages[-1]
    assert getattr(record, "request_id", None) == "req-log-1"
    assert getattr(record, "path", None) == "/health"
    assert getattr(record, "method", None) == "GET"
    assert getattr(record, "status_code", None) == 200


def test_request_logging_skips_static_paths(app, client, caplog):
    app.config["REQUEST_LOGGING_ENABLED"] = True

    with caplog.at_level(logging.INFO):
        response = client.get("/static/styles.css")

    assert response.status_code == 200
    messages = [record for record in caplog.records if record.getMessage() == "request completed"]
    assert not messages


def test_login_rate_limit_returns_429_after_threshold(app, client):
    # tests run with RATE_LIMIT_ENABLED=False by default; enable it here
    app.config["RATE_LIMIT_ENABLED"] = True
    app.config["LOGIN_RATE_LIMIT"] = "2/60"

    response1 = client.post(
        "/auth/login", data={"email": "a@example.com", "password": "x"}
    )
    response2 = client.post(
        "/auth/login", data={"email": "a@example.com", "password": "x"}
    )
    response3 = client.post(
        "/auth/login", data={"email": "a@example.com", "password": "x"}
    )

    assert response1.status_code in (200, 401)
    assert response2.status_code in (200, 401)
    assert response3.status_code == 429


def test_guest_lookup_rate_limit_returns_429_after_threshold(app, client):
    app.config["RATE_LIMIT_ENABLED"] = True
    app.config["GUEST_LOOKUP_RATE_LIMIT"] = "1/60"

    response1 = client.post(
        "/external/dashboard",
        data={"request_id": "", "guest_email": "guest@example.com"},
    )
    response2 = client.post(
        "/external/dashboard",
        data={"request_id": "", "guest_email": "guest@example.com"},
    )

    assert response1.status_code == 200
    assert response2.status_code == 429


def test_timestamped_webhook_signature_is_accepted_when_enabled(app, client, monkeypatch):
    app.config["WEBHOOK_SHARED_SECRET"] = "secret-123"
    app.config["WEBHOOK_REQUIRE_TIMESTAMP"] = True
    payload = {"hello": "world"}
    raw = json.dumps(payload).encode("utf-8")
    timestamp = "1893456000"
    sig = compute_webhook_signature(
        app.config["WEBHOOK_SHARED_SECRET"], raw, timestamp=timestamp
    )

    monkeypatch.setattr("app.security.time.time", lambda: 1893456000)

    response = client.post(
        "/integrations/incoming-webhook",
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": sig,
        },
    )

    assert response.status_code == 204


def test_timestamped_webhook_missing_timestamp_is_rejected_when_required(app, client):
    app.config["WEBHOOK_SHARED_SECRET"] = "secret-123"
    app.config["WEBHOOK_REQUIRE_TIMESTAMP"] = True
    raw = json.dumps({"hello": "world"}).encode("utf-8")
    sig = compute_webhook_signature(app.config["WEBHOOK_SHARED_SECRET"], raw)

    response = client.post(
        "/integrations/incoming-webhook",
        data=raw,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": sig},
    )

    assert response.status_code == 401


def test_apply_bulk_verification_params_normalizes_separator():
    params = apply_bulk_verification_params(
        {"other": "value"},
        verify_each_separated_value=True,
        value_separator="newline",
        bulk_input_hint="One item per line",
    )

    assert params["other"] == "value"
    assert params["verify_each_separated_value"] is True
    assert params["value_separator"] == "\n"
    assert params["bulk_input_hint"] == "One item per line"


def test_admin_console_uses_unified_shell_classes(app, client):
    user = User(
        email="admin-shell@example.com",
        name="Admin Shell",
        department="A",
        is_active=True,
        is_admin=True,
        password_hash=generate_password_hash("password"),
    )
    db.session.add(user)
    db.session.commit()

    login_response = client.post(
        "/auth/login",
        data={"email": "admin-shell@example.com", "password": "password"},
        follow_redirects=True,
    )
    assert login_response.status_code in (200, 302)

    response = client.get("/admin/")
    assert response.status_code == 200
    assert b"page-header" in response.data
    assert b"surface-panel" in response.data