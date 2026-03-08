from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import IntegrationEvent, SavedSearchView, User
from app.services.event_bus import mark_event_failed, publish_event


def _create_user(app, email, *, department="B", is_admin=False, password="secret"):
    with app.app_context():
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            department=department,
            is_active=True,
            is_admin=is_admin,
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, email, password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_user_can_save_search_view_and_see_it_on_dashboard(app, client):
    _create_user(app, "saved-view@example.com", department="B")
    rv = _login(client, "saved-view@example.com")
    assert rv.status_code == 200

    rv = client.post(
        "/search/saved",
        data={
            "name": "My breached queue",
            "q": "widget",
            "sla": "breached",
            "priority": "high",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"My breached queue" in rv.data

    with app.app_context():
        saved = SavedSearchView.query.filter_by(name="My breached queue").first()
        assert saved is not None
        assert saved.params["sla"] == "breached"
        assert saved.params["priority"] == "high"

    rv = client.get("/dashboard")
    assert rv.status_code == 200
    assert b"Personal dashboard shortcuts" in rv.data
    assert b"My breached queue" in rv.data

    with app.app_context():
        saved = SavedSearchView.query.filter_by(name="My breached queue").first()
        saved_id = saved.id

    rv = client.post(f"/search/saved/{saved_id}/default", follow_redirects=True)
    assert rv.status_code == 200
    with app.app_context():
        saved = db.session.get(SavedSearchView, saved_id)
        assert saved.is_default is True


def test_publish_event_and_failure_tracking_store_retry_metadata(app):
    with app.app_context():
        event = publish_event(
            "request.created",
            {"id": 123, "created_at": datetime(2026, 3, 8, 12, 0, 0)},
            destination_kind="webhook",
            provider_key="acme-erp",
        )
        assert event.correlation_id
        assert event.provider_key == "acme-erp"
        assert event.next_retry_at is not None
        assert event.payload_json["created_at"] == "2026-03-08T12:00:00"

        before = datetime.utcnow()
        mark_event_failed(event, RuntimeError("timeout from provider"))
        db.session.refresh(event)

        assert event.status == "failed"
        assert event.retry_count == 1
        assert event.last_attempt_at is not None
        assert event.next_retry_at is not None
        assert event.next_retry_at >= before
        assert "timeout from provider" in (event.last_error or "")


def test_admin_integration_event_page_shows_durable_event_fields(app, client):
    _create_user(app, "durability-admin@example.com", department="B", is_admin=True)
    with app.app_context():
        event = IntegrationEvent(
            event_name="request.updated",
            destination_kind="webhook",
            provider_key="crm-sync",
            correlation_id="corr-123",
            status="failed",
            retry_count=2,
            next_retry_at=datetime.utcnow() + timedelta(minutes=10),
            last_error="temporary outage",
        )
        db.session.add(event)
        db.session.commit()

    rv = _login(client, "durability-admin@example.com")
    assert rv.status_code == 200
    rv = client.get("/admin/integration_events")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "crm-sync" in html
    assert "corr-123" in html
    assert "Next retry" in html
