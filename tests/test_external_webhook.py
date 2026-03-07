import json
import hmac
import hashlib
from datetime import datetime

import pytest

from app.extensions import db
from app.models import (
    FormTemplate,
    DepartmentFormAssignment,
    Submission,
    Request as ReqModel,
)


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_external_form_callback_creates_request(client, app, monkeypatch):
    secret = "shhhhh"
    monkeypatch.setenv("WEBHOOK_SHARED_SECRET", secret)

    # create a template assigned to dept A
    with app.app_context():
        t = FormTemplate(
            name="External MS Form",
            description="msf",
            external_enabled=True,
            external_form_id="msf-1",
            external_provider="microsoft_forms",
        )
        db.session.add(t)
        db.session.commit()
        assign = DepartmentFormAssignment(template_id=t.id, department_name="A")
        db.session.add(assign)
        db.session.commit()

    payload = {
        "external_form_id": "msf-1",
        "form_response": {
            "title": "Create part",
            "description": "Please create part",
            "priority": "high",
            "request_type": "part_number",
            "donor_part_number": "D-1",
            "target_part_number": "T-2",
            "due_at": "2026-03-10T12:00:00Z",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(secret, body)
    resp = client.post(
        "/integrations/external-form-callback",
        data=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": sig},
    )
    assert resp.status_code == 200
    j = resp.get_json()
    assert j.get("ok") is True
    rid = j.get("created_request_id")
    assert rid is not None

    # verify Request and Submission exist
    with app.app_context():
        r = db.session.get(ReqModel, rid)
        assert r is not None
        subs = Submission.query.filter_by(request_id=rid).all()
        assert len(subs) == 1


def test_external_form_callback_invalid_signature(client, app, monkeypatch):
    secret = "shhhhh"
    monkeypatch.setenv("WEBHOOK_SHARED_SECRET", secret)
    payload = {"external_form_id": "nope", "form_response": {"title": "x"}}
    body = json.dumps(payload).encode("utf-8")
    # wrong sig
    resp = client.post(
        "/integrations/external-form-callback",
        data=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": "bad"},
    )
    assert resp.status_code == 401


def test_external_form_callback_template_not_external(client, app, monkeypatch):
    secret = "shhhhh"
    monkeypatch.setenv("WEBHOOK_SHARED_SECRET", secret)
    with app.app_context():
        t = FormTemplate(
            name="Not external",
            description="no",
            external_enabled=False,
            external_form_id="msf-2",
        )
        db.session.add(t)
        db.session.commit()

    payload = {"external_form_id": "msf-2", "form_response": {"title": "x"}}
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(secret, body)
    resp = client.post(
        "/integrations/external-form-callback",
        data=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": sig},
    )
    assert resp.status_code == 400
    j = resp.get_json()
    assert j.get("error") == "template_not_external"
