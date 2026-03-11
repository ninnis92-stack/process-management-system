import json

from app.extensions import db
from app.models import IntegrationConfig, IntegrationEvent


def test_webhook_provider_lookup(app, monkeypatch):
    """When an IntegrationEvent has a provider_key, connector worker should
    resolve an IntegrationConfig with matching key and call emit_webhook_event
    with the configured URL.
    """
    called = {}

    # stub emit_webhook_event used by connector_worker
    import app.services.connector_worker as cw

    def fake_emit(event_name, payload, url=None):
        called["event_name"] = event_name
        called["payload"] = payload
        called["url"] = url

    monkeypatch.setattr(cw, "emit_webhook_event", fake_emit)

    # create a webhook IntegrationConfig with a key
    cfg = IntegrationConfig(
        department="A",
        kind="webhook",
        enabled=True,
        config=json.dumps({"key": "acme", "url": "https://example.com/hook"}),
    )
    db.session.add(cfg)
    db.session.commit()

    ev = IntegrationEvent(
        event_name="automation.test",
        destination_kind="webhook",
        provider_key="acme",
        payload_json={},
    )
    db.session.add(ev)
    db.session.commit()

    processed = cw.process_pending_integration_events(limit=10)
    assert processed == 1
    assert called.get("url") == "https://example.com/hook"


def test_outbox_email_routes(app, monkeypatch):
    """Outbox email events should use EmailService and mark delivered when send succeeds."""
    import app.services.connector_worker as cw

    class FakeEmail:
        def send_email(self, recipients, subject, text, html=None):
            return {"ok": True}

    # patch EmailService factory used in the module
    monkeypatch.setattr(cw, "EmailService", lambda: FakeEmail())

    ev = IntegrationEvent(
        event_name="automation.email",
        destination_kind="outbox",
        payload_json={"to": "user@example.com", "subject": "Hello", "body": "World"},
    )
    db.session.add(ev)
    db.session.commit()

    processed = cw.process_pending_integration_events(limit=10)
    assert processed == 1


def test_outbox_slack_routes(app, monkeypatch):
    """Outbox slack events should prefer payload webhook, else provider config, and post via SlackService."""
    import app.services.connector_worker as cw

    posted = {}

    class FakeSlack:
        def post_message(self, webhook_url, payload):
            posted["webhook"] = webhook_url
            posted["payload"] = payload
            return {"ok": True}

    monkeypatch.setattr(cw, "SlackService", lambda: FakeSlack())

    # Case: payload includes slack_webhook directly
    ev = IntegrationEvent(
        event_name="automation.slack.notify",
        destination_kind="outbox",
        payload_json={"slack_webhook": "https://hooks.example.com/1", "text": "hi"},
    )
    db.session.add(ev)
    db.session.commit()
    processed = cw.process_pending_integration_events(limit=10)
    assert processed == 1
    assert posted.get("webhook") == "https://hooks.example.com/1"
