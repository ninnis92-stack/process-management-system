from werkzeug.security import generate_password_hash

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