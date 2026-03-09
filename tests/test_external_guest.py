from datetime import datetime, timedelta


def _future_due(hours=72):
    return (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


def test_guest_submission_without_description(client, app, monkeypatch):
    from app.models import Request, Submission

    monkeypatch.setattr(
        "app.external.routes._send_guest_email", lambda *args, **kwargs: None
    )

    resp = client.post(
        "/external/new",
        data={
            "guest_email": "guest@example.com",
            "guest_name": "Guesty",
            "title": "Need help",
            "request_type": "part_number",
            "donor_part_number": "",
            "target_part_number": "ABC",
            "no_donor_reason": "needs_create",
            "pricebook_status": "unknown",
            "pricebook_number": "PB-TEST",
            "priority": "medium",
            "due_at": _future_due(),
            "description": "",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert "/external/" in resp.headers.get("Location", "")

    with app.app_context():
        req = Request.query.one()
        assert req.description == ""
        sub = Submission.query.one()
        assert sub.details == ""


def test_guest_dashboard_lookup_redirects_on_match(client, app):
    from app.extensions import db
    from app.models import Request

    req = Request(
        title="Lookup me",
        request_type="part_number",
        description="something",
        priority="low",
        status="NEW_FROM_A",
        owner_department="B",
        submitter_type="guest",
        guest_email="guest@example.com",
        pricebook_status="unknown",
        due_at=datetime.utcnow() + timedelta(days=5),
    )
    req.ensure_guest_token()
    db.session.add(req)
    db.session.commit()

    resp = client.post(
        "/external/dashboard",
        data={"request_id": req.id, "guest_email": "guest@example.com"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert req.guest_access_token in resp.headers.get("Location", "")


def test_external_new_shows_process_flow_explainer(client):
    resp = client.get("/external/new")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Form, process flow, and department are separate choices" in html
    assert "Process flow preview" in html
    assert "Optional process flow" in html
