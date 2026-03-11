import pytest
from flask import current_app, jsonify

from app import create_app
from app.extensions import db


def test_health_and_ready_endpoint_return_ok(app, client):
    """Both liveness and readiness probes should return HTTP 200 with JSON."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("status") == "ok"

    resp2 = client.get("/ready")
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2 and data2.get("status") == "ok"
    # readiness payload should include a database component
    assert "components" in data2 and "database" in data2["components"]


def test_ready_endpoint_reports_unhealthy_if_db_throws(app, client, monkeypatch):
    """When DB connectivity fails the readiness probe should return non-OK."""

    # monkeypatch the DB session execute to raise an error
    class DummyException(Exception):
        pass

    monkeypatch.setattr(
        db.session,
        "execute",
        lambda *args, **kwargs: (_ for _ in ()).throw(DummyException("boom")),
    )

    resp = client.get("/ready")
    assert resp.status_code >= 500
    data = resp.get_json()
    assert data.get("status") == "unhealthy"
    assert "database" in data.get("components", {})
