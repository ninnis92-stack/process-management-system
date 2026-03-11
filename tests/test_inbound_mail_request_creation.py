import hashlib
import hmac
import json
from datetime import datetime, timedelta

from app.extensions import db
from app.models import SpecialEmailConfig, Request as ReqModel, User

# reuse helpers from site navigation tests for login
from tests.test_site_navigation import _create_user, _login
from app.models import FormTemplate, FormField, DepartmentFormAssignment


def _sig(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def test_inbound_mail_creates_guest_request(app, client):
    secret = "test-secret"
    app.config["WEBHOOK_SHARED_SECRET"] = secret

    with app.app_context():
        cfg = SpecialEmailConfig.get()
        cfg.enabled = True
        cfg.request_form_email = "requests@example.com"
        # ensure default watchers list is empty for this baseline test
        cfg.request_form_default_watchers = None
        cfg.request_form_add_original_sender = False
        db.session.commit()

    payload = {
        "from": "guest.sender@example.com",
        "to": "requests@example.com",
        "subject": "title=Email Guest Request;request_type=both;priority=high",
        "body": "Guest description text",
    }
    raw = json.dumps(payload).encode("utf-8")

    rv = client.post(
        "/integrations/inbound-mail",
        data=raw,
        content_type="application/json",
        headers={"X-Webhook-Signature": _sig(secret, raw)},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["created_request_id"] is not None

    with app.app_context():
        req = db.session.get(ReqModel, data["created_request_id"])
        assert req is not None
        assert req.submitter_type == "guest"
        assert req.guest_email == "guest.sender@example.com"
        assert req.title == "Email Guest Request"
        # baseline test: original_sender and watchers should not be set
        assert getattr(req, "original_sender", None) is None
        assert getattr(req, "watcher_emails", None) in (None, [])


def test_inbound_mail_creates_user_request_for_sso_sender(app, client):
    secret = "test-secret"
    app.config["WEBHOOK_SHARED_SECRET"] = secret

    with app.app_context():
        u = User(
            sso_sub="sso-123",
            email="sso.user@example.com",
            name="SSO User",
            password_hash="x",
            department="C",
            is_active=True,
        )
        db.session.add(u)
        db.session.commit()

        cfg = SpecialEmailConfig.get()
        cfg.enabled = True
        cfg.request_form_email = "requests@example.com"
        cfg.request_form_department = "A"
        db.session.commit()

        uid = u.id

    payload = {
        "from": "sso.user@example.com",
        "to": "requests@example.com",
        "subject": "title=Email SSO Request;due_at="
        + (datetime.utcnow() + timedelta(days=3)).isoformat(),
        "body": "SSO request description",
    }
    raw = json.dumps(payload).encode("utf-8")

    rv = client.post(
        "/integrations/inbound-mail",
        data=raw,
        content_type="application/json",
        headers={"X-Webhook-Signature": _sig(secret, raw)},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["created_request_id"] is not None

    with app.app_context():
        req = db.session.get(ReqModel, data["created_request_id"])
        user = db.session.get(User, uid)
        assert req is not None
        assert req.submitter_type == "user"
        assert req.created_by_user_id == uid
        # Admin-configured department override for recognized sender is applied.
        assert user.department == "A"
        # user test should not affect original/watcher defaults
        assert getattr(req, "original_sender", None) is None
        assert getattr(req, "watcher_emails", None) in (None, [])


def test_inbound_mail_records_original_sender_and_notifies_watchers(app, client, monkeypatch):
    secret = "test-secret"
    app.config["WEBHOOK_SHARED_SECRET"] = secret

    sent_emails = []

    def fake_send_email(self, recipients, subject, text, html=None):
        sent_emails.append({"to": recipients, "subject": subject, "body": text})
        return {"ok": True, "skipped": [], "error": None}

    monkeypatch.setattr("app.services.emailer.EmailService.send_email", fake_send_email)

    with app.app_context():
        cfg = SpecialEmailConfig.get()
        cfg.enabled = True
        cfg.request_form_email = "requests@example.com"
        cfg.request_form_add_original_sender = True
        cfg.request_form_default_watchers = ["watcher1@example.com", "watcher2@example.com"]
        db.session.commit()

    payload = {
        "from": "orig@sender.com",
        "to": "requests@example.com",
        "subject": "title=Forwarded request;priority=low",
        "body": "Please handle this",
    }
    raw = json.dumps(payload).encode("utf-8")

    rv = client.post(
        "/integrations/inbound-mail",
        data=raw,
        content_type="application/json",
        headers={"X-Webhook-Signature": _sig(secret, raw)},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    with app.app_context():
        req = db.session.get(ReqModel, data["created_request_id"])
        assert req.original_sender == "orig@sender.com"
        assert set(req.watcher_emails or []) == {"watcher1@example.com", "watcher2@example.com", "orig@sender.com"}
    # ensure notification emails were sent to all watchers
    assert any("watcher1@example.com" in e["to"] for e in sent_emails)
    assert any("orig@sender.com" in e["to"] for e in sent_emails)

    # the request detail UI should expose the original sender and watcher list
    # create and login an admin so we can view the admin detail page
    _create_user(app, email="nav-admin@example.com", is_admin=True)
    login_resp = _login(client, "nav-admin@example.com")
    assert login_resp.status_code == 200
    rv2 = client.get(f"/requests/{req.id}")
    assert rv2.status_code == 200
    html2 = rv2.get_data(as_text=True)
    assert "Orig sender" in html2
    assert "watcher1@example.com" in html2


def test_inbound_mail_rejects_invalid_fields_when_validation_enabled(app, client):
    secret = "test-secret"
    app.config["WEBHOOK_SHARED_SECRET"] = secret

    with app.app_context():
        cfg = SpecialEmailConfig.get()
        cfg.enabled = True
        cfg.request_form_email = "requests@example.com"
        cfg.request_form_field_validation_enabled = True
        db.session.commit()

    payload = {
        "from": "guest.sender@example.com",
        "to": "requests@example.com",
        "subject": "title=Invalid Request;request_type=not_a_valid_type",
        "body": "Invalid request type should be rejected",
    }
    raw = json.dumps(payload).encode("utf-8")

    rv = client.post(
        "/integrations/inbound-mail",
        data=raw,
        content_type="application/json",
        headers={"X-Webhook-Signature": _sig(secret, raw)},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["rejected"] is True
    assert data["created_request_id"] is None
    assert "request_type" in data["invalid_fields"]

    with app.app_context():
        req = ReqModel.query.filter_by(title="Invalid Request").first()
        assert req is None


def test_inbound_mail_allows_invalid_fields_when_validation_disabled(app, client):
    secret = "test-secret"
    app.config["WEBHOOK_SHARED_SECRET"] = secret

    with app.app_context():
        cfg = SpecialEmailConfig.get()
        cfg.enabled = True
        cfg.request_form_email = "requests@example.com"
        cfg.request_form_field_validation_enabled = False
        db.session.commit()

    payload = {
        "from": "guest.sender@example.com",
        "to": "requests@example.com",
        "subject": "title=Fallback Request;request_type=not_a_valid_type",
        "body": "Should still create request using fallback when strict validation is off",
    }
    raw = json.dumps(payload).encode("utf-8")

    rv = client.post(
        "/integrations/inbound-mail",
        data=raw,
        content_type="application/json",
        headers={"X-Webhook-Signature": _sig(secret, raw)},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["rejected"] is False
    assert data["created_request_id"] is not None
    assert "request_type" in data["invalid_fields"]

    with app.app_context():
        req = db.session.get(ReqModel, data["created_request_id"])
        assert req is not None
        assert req.request_type == "both"


def test_out_of_stock_notification_only_mode(monkeypatch, app, client):
    secret = "test-secret"
    app.config["WEBHOOK_SHARED_SECRET"] = secret

    with app.app_context():
        u = User(
            sso_sub="sso-456",
            email="stock.user@example.com",
            name="Stock User",
            password_hash="x",
            department="B",
            is_active=True,
        )
        db.session.add(u)
        cfg = SpecialEmailConfig.get()
        cfg.enabled = True
        cfg.request_form_email = "requests@example.com"
        cfg.request_form_inventory_out_of_stock_notify_enabled = True
        cfg.request_form_inventory_out_of_stock_notify_mode = "notification"
        cfg.request_form_inventory_out_of_stock_message = (
            "Inventory issue:\n{out_of_stock_fields}"
        )
        db.session.commit()

    def _always_oos(self, value):
        return False

    monkeypatch.setattr(
        "app.services.inventory.InventoryService.validate_part_number", _always_oos
    )

    calls = {"notify": 0, "email": 0}

    def _mock_notify(
        users,
        title,
        body=None,
        url=None,
        ntype="generic",
        request_id=None,
        allow_email=True,
    ):
        calls["notify"] += 1
        assert title == "Inventory out-of-stock notice"
        assert "donor_part_number" in (body or "")
        return None

    def _mock_email(sender_email, out_of_stock_fields, message=None):
        calls["email"] += 1
        return True

    monkeypatch.setattr("app.notifcations.notify_users", _mock_notify)
    monkeypatch.setattr(
        "app.notifcations.send_request_form_inventory_out_of_stock_notice", _mock_email
    )

    payload = {
        "from": "stock.user@example.com",
        "to": "requests@example.com",
        "subject": "title=OOS Notify Only;request_type=both;donor_part_number=ABC123",
        "body": "Check out-of-stock handling",
    }
    raw = json.dumps(payload).encode("utf-8")

    rv = client.post(
        "/integrations/inbound-mail",
        data=raw,
        content_type="application/json",
        headers={"X-Webhook-Signature": _sig(secret, raw)},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["out_of_stock_notified"] is True
    assert data["out_of_stock_notify_mode"] == "notification"
    assert "donor_part_number" in data["out_of_stock_fields"]
    assert calls["notify"] == 1
    assert calls["email"] == 0


def test_out_of_stock_email_only_mode_uses_custom_message(monkeypatch, app, client):
    secret = "test-secret"
    app.config["WEBHOOK_SHARED_SECRET"] = secret

    with app.app_context():
        cfg = SpecialEmailConfig.get()
        cfg.enabled = True
        cfg.request_form_email = "requests@example.com"
        cfg.request_form_inventory_out_of_stock_notify_enabled = True
        cfg.request_form_inventory_out_of_stock_notify_mode = "email"
        cfg.request_form_inventory_out_of_stock_message = (
            "Custom OOS message:\n{out_of_stock_fields}"
        )
        db.session.commit()

    def _always_oos(self, value):
        return False

    monkeypatch.setattr(
        "app.services.inventory.InventoryService.validate_part_number", _always_oos
    )

    calls = {"notify": 0, "email": 0, "message": None}

    def _mock_notify(
        users,
        title,
        body=None,
        url=None,
        ntype="generic",
        request_id=None,
        allow_email=True,
    ):
        calls["notify"] += 1
        return None

    def _mock_email(sender_email, out_of_stock_fields, message=None):
        calls["email"] += 1
        calls["message"] = message
        assert sender_email == "guest.sender@example.com"
        assert "donor_part_number" in out_of_stock_fields
        return True

    monkeypatch.setattr("app.notifcations.notify_users", _mock_notify)
    monkeypatch.setattr(
        "app.notifcations.send_request_form_inventory_out_of_stock_notice", _mock_email
    )

    payload = {
        "from": "guest.sender@example.com",
        "to": "requests@example.com",
        "subject": "title=OOS Email Only;request_type=both;donor_part_number=ABC123",
        "body": "Check email out-of-stock handling",
    }
    raw = json.dumps(payload).encode("utf-8")

    rv = client.post(
        "/integrations/inbound-mail",
        data=raw,
        content_type="application/json",
        headers={"X-Webhook-Signature": _sig(secret, raw)},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["out_of_stock_notified"] is True
    assert data["out_of_stock_notify_mode"] == "email"
    assert calls["notify"] == 0
    assert calls["email"] == 1
    assert calls["message"] == "Custom OOS message:\n{out_of_stock_fields}"




def test_inbound_mail_uses_sso_owner_email_when_inbox_not_set(app, client):
    secret = "test-secret"
    app.config["WEBHOOK_SHARED_SECRET"] = secret

    with app.app_context():
        owner = User(
            sso_sub="sso-owner-1",
            email="owner.sso@example.com",
            name="Owner",
            password_hash="x",
            department="B",
            is_active=True,
        )
        db.session.add(owner)
        db.session.commit()

        cfg = SpecialEmailConfig.get()
        cfg.enabled = True
        cfg.request_form_email = None
        cfg.request_form_user_id = owner.id
        db.session.commit()

    payload_ok = {
        "from": "guest.sender@example.com",
        "to": "owner.sso@example.com",
        "subject": "title=Owner Inbox Request;request_type=both",
        "body": "should be accepted through owner email fallback",
    }
    raw_ok = json.dumps(payload_ok).encode("utf-8")
    rv_ok = client.post(
        "/integrations/inbound-mail",
        data=raw_ok,
        content_type="application/json",
        headers={"X-Webhook-Signature": _sig(secret, raw_ok)},
    )
    assert rv_ok.status_code == 200
    data_ok = rv_ok.get_json()
    assert data_ok.get("created_request_id") is not None

    payload_skip = {
        "from": "guest.sender@example.com",
        "to": "other-inbox@example.com",
        "subject": "title=Wrong Inbox Request;request_type=both",
        "body": "should be skipped by recipient guard",
    }
    raw_skip = json.dumps(payload_skip).encode("utf-8")
    rv_skip = client.post(
        "/integrations/inbound-mail",
        data=raw_skip,
        content_type="application/json",
        headers={"X-Webhook-Signature": _sig(secret, raw_skip)},
    )
    assert rv_skip.status_code == 200
    data_skip = rv_skip.get_json()
    assert data_skip.get("skipped") == "recipient_mismatch"


def test_autoresponder_uses_department_template_fields(monkeypatch, app):
    from app import notifcations

    with app.app_context():
        cfg = SpecialEmailConfig.get()
        cfg.enabled = True
        cfg.request_form_department = "A"

        template = FormTemplate(name="Dept A Email Template", description="")
        db.session.add(template)
        db.session.flush()
        db.session.add(
            FormField(
                template_id=template.id,
                name="part_code",
                label="Part Code",
                field_type="text",
                required=True,
            )
        )
        db.session.add(
            FormField(
                template_id=template.id,
                name="priority",
                label="Priority",
                field_type="select",
                required=True,
            )
        )
        db.session.flush()
        db.session.add(
            DepartmentFormAssignment(template_id=template.id, department_name="A")
        )
        db.session.commit()

    sent = {"subject": None, "body": None}

    def _mock_send(recipients_map, subject, body, html=None, request_id=None):
        sent["subject"] = subject
        sent["body"] = body
        return None

    monkeypatch.setattr("app.notifcations._send_emails_async", _mock_send)

    ok = notifcations.send_request_form_autoresponder("guest.sender@example.com")
    assert ok is True
    assert sent["subject"] == "Request form: instructions to submit via subject"
    assert "part_code=" in (sent["body"] or "")
    assert "priority=" in (sent["body"] or "")


def test_inbound_mail_rejects_missing_required_department_field_when_strict(
    app, client
):
    secret = "test-secret"
    app.config["WEBHOOK_SHARED_SECRET"] = secret

    with app.app_context():
        cfg = SpecialEmailConfig.get()
        cfg.enabled = True
        cfg.request_form_email = "requests@example.com"
        cfg.request_form_department = "A"
        cfg.request_form_field_validation_enabled = True

        template = FormTemplate(name="Dept A Validation Template", description="")
        db.session.add(template)
        db.session.flush()
        db.session.add(
            FormField(
                template_id=template.id,
                name="part_code",
                label="Part Code",
                field_type="text",
                required=True,
            )
        )
        db.session.add(
            DepartmentFormAssignment(template_id=template.id, department_name="A")
        )
        db.session.commit()

    payload = {
        "from": "guest.sender@example.com",
        "to": "requests@example.com",
        "subject": "title=Missing Dept Field",
        "body": "This should fail strict template validation",
    }
    raw = json.dumps(payload).encode("utf-8")

    rv = client.post(
        "/integrations/inbound-mail",
        data=raw,
        content_type="application/json",
        headers={"X-Webhook-Signature": _sig(secret, raw)},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["rejected"] is True
    assert "part_code" in data["invalid_fields"]
