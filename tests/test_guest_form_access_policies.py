import json
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import GuestForm, Request, User


def _future_due(hours=72):
    return (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


def _base_guest_payload(email):
    return {
        "guest_email": email,
        "guest_name": "Guest Submitter",
        "title": "Access policy test",
        "request_type": "part_number",
        "donor_part_number": "",
        "target_part_number": "ABC123",
        "no_donor_reason": "needs_create",
        "pricebook_status": "unknown",
        "priority": "medium",
        "due_at": _future_due(),
        "description": "policy validation",
        "owner_department": "B",
        "workflow_id": 0,
    }


def _login_admin(client, email="admin@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_admin_guest_form_can_store_access_policy_fields(app, client):
    with app.app_context():
        admin = User(
            email="admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

    rv = _login_admin(client)
    assert rv.status_code == 200

    resp = client.post(
        "/admin/guest_forms/new",
        data={
            "name": "Partner Intake",
            "slug": "partner-intake",
            "template_id": 0,
            "owner_department": "B",
            "access_policy": "approved_sso_domains",
            "allowed_email_domains": "partner.com\nsubsidiary.org",
            "credential_requirements_json": json.dumps(
                {"claim_path": "organization", "allowed_values": ["partner-org"]}
            ),
            "layout": "compact",
            "is_default": "y",
            "active": "y",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302

    with app.app_context():
        form = GuestForm.query.filter_by(slug="partner-intake").first()
        assert form is not None
        assert form.normalized_access_policy == "approved_sso_domains"
        assert form.require_sso is True
        assert form.allowed_email_domain_list == ["partner.com", "subsidiary.org"]
        assert form.credential_requirements == {
            "claim_path": "organization",
            "allowed_values": ["partner-org"],
        }
        # layout value persisted
        assert form.layout == "compact"

    list_page = client.get("/admin/guest_forms")
    assert list_page.status_code == 200
    html = list_page.get_data(as_text=True)
    assert "Guest Request Forms" in html
    assert "request form template" in html.lower()


def test_guest_form_layout_applied_to_ui(app, client, monkeypatch):
    # create a guest form with a non-standard layout and verify the class appears
    with app.app_context():
        gf = GuestForm(
            name="Layout Test",
            slug="layout-test",
            owner_department="B",
            active=True,
            layout="spacious",
        )
        db.session.add(gf)
        db.session.commit()

    rv = client.get("/external/new?guest_form=layout-test")
    html = rv.get_data(as_text=True)
    assert "guest-form-shell" in html
    assert "layout-spacious" in html
    # verify fallback without query parameter uses standard layout
    rv2 = client.get("/external/new")
    html2 = rv2.get_data(as_text=True)
    assert "layout-standard" in html2


def test_approved_sso_domains_policy_enforced(app, client, monkeypatch):
    monkeypatch.setattr(
        "app.external.routes._send_guest_email", lambda *args, **kwargs: None
    )

    with app.app_context():
        form = GuestForm(
            name="Partner Only",
            slug="partner-only",
            owner_department="B",
            active=True,
            access_policy="approved_sso_domains",
            require_sso=True,
            allowed_email_domains="partner.com",
        )
        user = User(
            email="member@partner.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            sso_sub="oidc|partner-member",
        )
        db.session.add_all([form, user])
        db.session.commit()

    denied = client.post(
        "/external/new?guest_form=partner-only",
        data=_base_guest_payload("outside@example.com"),
        follow_redirects=True,
    )
    assert denied.status_code == 200
    denied_text = denied.get_data(as_text=True)
    assert (
        "approved organization" in denied_text
        or "approved SSO" in denied_text
        or "SSO-linked account" in denied_text
    )

    with app.app_context():
        assert Request.query.count() == 0

    allowed = client.post(
        "/external/new?guest_form=partner-only",
        data=_base_guest_payload("member@partner.com"),
        follow_redirects=False,
    )
    assert allowed.status_code == 302

    with app.app_context():
        assert Request.query.count() == 1


def test_unaffiliated_only_policy_enforced(app, client, monkeypatch):
    monkeypatch.setattr(
        "app.external.routes._send_guest_email", lambda *args, **kwargs: None
    )

    with app.app_context():
        form = GuestForm(
            name="Unaffiliated Intake",
            slug="unaffiliated-intake",
            owner_department="C",
            active=True,
            access_policy="unaffiliated_only",
            require_sso=False,
            allowed_email_domains="partner.com,subsidiary.org",
        )
        affiliated = User(
            email="member@partner.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            sso_sub="oidc|affiliated",
        )
        db.session.add_all([form, affiliated])
        db.session.commit()

    denied = client.post(
        "/external/new?guest_form=unaffiliated-intake",
        data=_base_guest_payload("member@partner.com"),
        follow_redirects=True,
    )
    assert denied.status_code == 200
    assert b"reserved for unaffiliated submitters" in denied.data

    allowed = client.post(
        "/external/new?guest_form=unaffiliated-intake",
        data=_base_guest_payload("freelancer@example.net"),
        follow_redirects=False,
    )
    assert allowed.status_code == 302

    with app.app_context():
        assert Request.query.count() == 1
