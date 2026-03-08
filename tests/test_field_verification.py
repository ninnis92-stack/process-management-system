import pytest
from werkzeug.security import generate_password_hash
from app.models import (
    User,
    FormTemplate,
    FormField,
    DepartmentFormAssignment,
    FieldVerification,
    Submission,
    Attachment,
    IntegrationConfig,
)
from app.extensions import db


class DummyInv:
    def validate_part_number(self, pn):
        return pn == "VALID123"

    def validate_sales_list_number(self, n):
        return n == "SKU-1"


class DummyHTTPResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = str(payload)

    def json(self):
        return self._payload


def test_field_verification_inventory(app, client, monkeypatch):
    # create a user in Dept A and login
    u = User(
        email="verifier@example.com",
        name="Verifier",
        department="A",
        is_active=True,
        password_hash=generate_password_hash("password"),
    )
    db.session.add(u)
    db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "verifier@example.com", "password": "password"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    # create template with a field
    t = FormTemplate(name="InvTemplate", description="Inventory test")
    db.session.add(t)
    db.session.commit()
    f = FormField(
        template_id=t.id,
        name="donor_part_number",
        label="Donor PN",
        field_type="text",
        required=True,
    )
    db.session.add(f)
    db.session.commit()

    # assign to Dept A
    a = DepartmentFormAssignment(template_id=t.id, department_name="A")
    db.session.add(a)
    db.session.commit()

    # map field to inventory provider
    fv = FieldVerification(
        field_id=f.id, provider="inventory", external_key="donor_part_number"
    )
    db.session.add(fv)
    db.session.commit()

    # enable external verification for the test and monkeypatch the InventoryService
    app.config["ENABLE_EXTERNAL_VERIFICATION"] = True

    monkeypatch.setattr("app.services.field_verification.InventoryService", lambda: DummyInv())

    # submit valid PN -> should pass verification
    data = {"donor_part_number": "VALID123", "due_at": "2030-01-01"}
    rv = client.post("/requests/new", data=data, follow_redirects=True)
    assert rv.status_code in (200, 302)

    # check latest submission has verification ok
    sub = Submission.query.order_by(Submission.created_at.desc()).first()
    assert sub is not None
    assert (
        sub.data.get("_verifications", {}).get("donor_part_number", {}).get("ok")
        is True
    )

    # submit invalid PN -> verification false
    data = {"donor_part_number": "BAD", "due_at": "2030-01-01"}
    rv = client.post("/requests/new", data=data, follow_redirects=True)
    assert rv.status_code in (200, 302)
    sub2 = Submission.query.order_by(Submission.created_at.desc()).first()
    assert sub2 is not None
    assert (
        sub2.data.get("_verifications", {}).get("donor_part_number", {}).get("ok")
        is False
    )


def test_bulk_separated_field_verification_and_hint(app, client, monkeypatch):
    u = User(
        email="bulk@example.com",
        name="Bulk",
        department="A",
        is_active=True,
        password_hash=generate_password_hash("password"),
    )
    db.session.add(u)
    db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "bulk@example.com", "password": "password"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    t = FormTemplate(name="Bulk Template", description="Bulk inventory test")
    db.session.add(t)
    db.session.commit()
    f = FormField(
        template_id=t.id,
        name="sales_skus",
        label="Sales SKUs",
        field_type="text",
        required=True,
    )
    db.session.add(f)
    db.session.commit()

    a = DepartmentFormAssignment(template_id=t.id, department_name="A")
    db.session.add(a)
    db.session.commit()

    fv = FieldVerification(
        field_id=f.id,
        provider="inventory",
        external_key="sales_list_number",
        params={
            "verify_each_separated_value": True,
            "value_separator": ",",
            "bulk_input_hint": "Enter one SKU per value, separated by commas.",
        },
    )
    db.session.add(fv)
    db.session.commit()

    monkeypatch.setattr("app.services.field_verification.InventoryService", lambda: DummyInv())

    rv = client.get("/requests/new")
    assert rv.status_code == 200
    assert b"Enter one SKU per value, separated by commas." in rv.data

    rv = client.post(
        "/requests/new",
        data={"sales_skus": "SKU-1, SKU-1", "due_at": "2030-01-01"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)
    sub = Submission.query.order_by(Submission.created_at.desc()).first()
    assert sub is not None
    result = sub.data.get("_verifications", {}).get("sales_skus", {})
    assert result.get("bulk") is True
    assert result.get("count") == 2
    assert result.get("ok") is True

    rv = client.post(
        "/requests/new",
        data={"sales_skus": "SKU-1, BAD", "due_at": "2030-01-01"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)
    sub2 = Submission.query.order_by(Submission.created_at.desc()).first()
    assert sub2 is not None
    result2 = sub2.data.get("_verifications", {}).get("sales_skus", {})
    assert result2.get("bulk") is True
    assert result2.get("ok") is False
    assert [item.get("ok") for item in result2.get("items", [])] == [True, False]


def test_field_verification_routes_to_tracker_handle_by_content(app, client, monkeypatch):
        u = User(
                email="tracker@example.com",
                name="Tracker",
                department="A",
                is_active=True,
                password_hash=generate_password_hash("password"),
        )
        db.session.add(u)
        db.session.commit()

        rv = client.post(
                "/auth/login",
                data={"email": "tracker@example.com", "password": "password"},
                follow_redirects=True,
        )
        assert rv.status_code in (200, 302)

        t = FormTemplate(name="Tracker Template", description="Realtime tracker test")
        db.session.add(t)
        db.session.commit()
        f = FormField(
                template_id=t.id,
                name="employee_identifier",
                label="Employee Identifier",
                field_type="text",
                required=True,
        )
        db.session.add(f)
        db.session.commit()

        a = DepartmentFormAssignment(template_id=t.id, department_name="A")
        db.session.add(a)
        db.session.commit()

        fv = FieldVerification(
                field_id=f.id,
                provider="verification",
                external_key="employee_identifier",
        )
        db.session.add(fv)
        db.session.commit()

        cfg = IntegrationConfig(
                department="A",
                kind="verification",
                enabled=True,
                config="""
                {
                    "provider": "generic_verification",
                    "routing": {
                        "default_tracker": "erp",
                        "rules": [
                            {
                                "name": "ACME IDs",
                                "tracker": "acme",
                                "external_keys": ["employee_identifier"],
                                "starts_with": ["ACME-"]
                            }
                        ]
                    },
                    "trackers": {
                        "erp": {
                            "endpoints": {
                                "base_url": "https://erp.example.com",
                                "validate": "/verify"
                            },
                            "request": {
                                "method": "GET",
                                "payload_location": "query",
                                "query_template": {"value": "{value}", "field": "{external_key}"}
                            },
                            "response": {
                                "ok_path": "ok",
                                "detail_path": "details"
                            }
                        },
                        "acme": {
                            "endpoints": {
                                "base_url": "https://acme.example.com",
                                "validate": "/verify"
                            },
                            "request": {
                                "method": "GET",
                                "payload_location": "query",
                                "query_template": {"identifier": "{value}"}
                            },
                            "response": {
                                "ok_path": "valid",
                                "detail_path": "payload"
                            }
                        }
                    }
                }
                """,
        )
        db.session.add(cfg)
        db.session.commit()

        calls = []

        def fake_request(self, method, url, **kwargs):
                calls.append({"method": method, "url": url, "kwargs": kwargs})
                if "acme.example.com" in url:
                        return DummyHTTPResponse({"valid": True, "payload": {"source": "acme"}})
                return DummyHTTPResponse({"ok": True, "details": {"source": "erp"}})

        monkeypatch.setattr("requests.sessions.Session.request", fake_request)

        rv = client.post(
                "/requests/new",
                data={"employee_identifier": "ACME-42", "due_at": "2030-01-01"},
                follow_redirects=True,
        )
        assert rv.status_code in (200, 302)

        sub = Submission.query.order_by(Submission.created_at.desc()).first()
        assert sub is not None
        result = sub.data.get("_verifications", {}).get("employee_identifier", {})
        assert result.get("ok") is True
        assert result.get("tracker_handle") == "acme"
        assert result.get("matched_rule") == "ACME IDs"
        assert result.get("details", {}).get("source") == "acme"
        assert calls[-1]["url"] == "https://acme.example.com/verify"
        assert calls[-1]["kwargs"]["params"]["identifier"] == "ACME-42"

        rv = client.post(
                "/requests/new",
                data={"employee_identifier": "EMP-7", "due_at": "2030-01-01"},
                follow_redirects=True,
        )
        assert rv.status_code in (200, 302)

        sub2 = Submission.query.order_by(Submission.created_at.desc()).first()
        assert sub2 is not None
        result2 = sub2.data.get("_verifications", {}).get("employee_identifier", {})
        assert result2.get("ok") is True
        assert result2.get("tracker_handle") == "erp"
        assert result2.get("details", {}).get("source") == "erp"
        assert calls[-1]["url"] == "https://erp.example.com/verify"
        assert calls[-1]["kwargs"]["params"]["value"] == "EMP-7"


def test_template_prefill_endpoint_returns_linked_values(app, client, monkeypatch):
    u = User(
        email="prefill@example.com",
        name="Prefill",
        department="A",
        is_active=True,
        password_hash=generate_password_hash("password"),
    )
    db.session.add(u)
    db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "prefill@example.com", "password": "password"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    t = FormTemplate(
        name="Prefill Template",
        description="Lookup-driven prefill",
        verification_prefill_enabled=True,
    )
    db.session.add(t)
    db.session.commit()

    source = FormField(
        template_id=t.id,
        name="employee_id",
        label="Employee ID",
        field_type="text",
        required=True,
    )
    target = FormField(
        template_id=t.id,
        name="employee_name",
        label="Employee Name",
        field_type="text",
        required=True,
    )
    db.session.add(source)
    db.session.add(target)
    db.session.commit()

    db.session.add(DepartmentFormAssignment(template_id=t.id, department_name="A"))
    db.session.add(
        FieldVerification(
            field_id=source.id,
            provider="verification",
            external_key="employee_id",
            params={
                "prefill_enabled": True,
                "prefill_targets": {"employee_name": "details.name"},
            },
        )
    )
    db.session.add(
        IntegrationConfig(
            department="A",
            kind="verification",
            enabled=True,
            config="""
            {
              "provider": "generic_verification",
              "routing": {"default_tracker": "directory"},
              "trackers": {
                "directory": {
                  "endpoints": {"base_url": "https://directory.example.com", "validate": "/lookup"},
                  "request": {
                    "method": "GET",
                    "payload_location": "query",
                    "query_template": {"employee_id": "{value}"}
                  },
                  "response": {
                    "ok_path": "ok",
                    "detail_path": "details"
                  }
                }
              }
            }
            """,
        )
    )
    db.session.commit()

    def fake_request(self, method, url, **kwargs):
        return DummyHTTPResponse({"ok": True, "details": {"name": "Ada Lovelace"}})

    monkeypatch.setattr("requests.sessions.Session.request", fake_request)

    rv = client.post(
        "/requests/template-prefill",
        json={"field_name": "employee_id", "values": {"employee_id": "EMP-1"}},
    )
    assert rv.status_code == 200
    payload = rv.get_json()
    assert payload["result"]["ok"] is True
    assert payload["prefills"]["employee_name"] == "Ada Lovelace"


def test_dynamic_submission_applies_verified_prefills_before_required_check(app, client, monkeypatch):
    u = User(
        email="prefill-submit@example.com",
        name="Prefill Submit",
        department="A",
        is_active=True,
        password_hash=generate_password_hash("password"),
    )
    db.session.add(u)
    db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "prefill-submit@example.com", "password": "password"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    t = FormTemplate(
        name="Verified Prefill Submit",
        description="Required targets can be filled from verification",
        verification_prefill_enabled=True,
    )
    db.session.add(t)
    db.session.commit()

    source = FormField(
        template_id=t.id,
        name="employee_id",
        label="Employee ID",
        field_type="text",
        required=True,
    )
    target_name = FormField(
        template_id=t.id,
        name="employee_name",
        label="Employee Name",
        field_type="text",
        required=True,
    )
    target_email = FormField(
        template_id=t.id,
        name="employee_email",
        label="Employee Email",
        field_type="text",
        required=False,
    )
    db.session.add_all([source, target_name, target_email])
    db.session.commit()

    db.session.add(DepartmentFormAssignment(template_id=t.id, department_name="A"))
    db.session.add(
        FieldVerification(
            field_id=source.id,
            provider="verification",
            external_key="employee_id",
            params={
                "prefill_enabled": True,
                "prefill_targets": {
                    "employee_name": "details.name",
                    "employee_email": "details.email"
                },
            },
        )
    )
    db.session.add(
        IntegrationConfig(
            department="A",
            kind="verification",
            enabled=True,
            config="""
            {
              "provider": "generic_verification",
              "routing": {"default_tracker": "directory"},
              "trackers": {
                "directory": {
                  "endpoints": {"base_url": "https://directory.example.com", "validate": "/lookup"},
                  "request": {
                    "method": "GET",
                    "payload_location": "query",
                    "query_template": {"employee_id": "{value}"}
                  },
                  "response": {
                    "ok_path": "ok",
                    "detail_path": "details"
                  }
                }
              }
            }
            """,
        )
    )
    db.session.commit()

    def fake_request(self, method, url, **kwargs):
        return DummyHTTPResponse(
            {
                "ok": True,
                "details": {
                    "name": "Grace Hopper",
                    "email": "grace@example.com",
                },
            }
        )

    monkeypatch.setattr("requests.sessions.Session.request", fake_request)

    rv = client.get("/requests/new")
    assert rv.status_code == 200
    assert b"Verification auto-fill enabled" in rv.data
    assert b"employee_name" in rv.data

    rv = client.post(
        "/requests/new",
        data={"employee_id": "EMP-9", "due_at": "2030-01-01"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    sub = Submission.query.order_by(Submission.created_at.desc()).first()
    assert sub is not None
    assert sub.data.get("employee_id") == "EMP-9"
    assert sub.data.get("employee_name") == "Grace Hopper"
    assert sub.data.get("employee_email") == "grace@example.com"
    assert sub.data.get("_verifications", {}).get("employee_id", {}).get("ok") is True
    assert (
        sub.data.get("_auto_prefills", {})
        .get("employee_id", {})
        .get("employee_name", {})
        .get("value")
        == "Grace Hopper"
    )
