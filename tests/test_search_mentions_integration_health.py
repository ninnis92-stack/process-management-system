from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import IntegrationEvent, JobRecord, Notification, Request, User


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


def test_comment_mentions_create_direct_notification(app, client):
    actor_id = _create_user(app, "commenter@example.com", department="B")
    mentioned_id = _create_user(app, "teammate@example.com", department="B")

    with app.app_context():
        req = Request(
            title="Mention request",
            request_type="part_number",
            description="Needs discussion",
            priority="medium",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            created_by_user_id=actor_id,
            pricebook_status="unknown",
            due_at=datetime.utcnow() + timedelta(days=3),
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id

    rv = _login(client, "commenter@example.com")
    assert rv.status_code == 200

    rv = client.post(
        f"/requests/{req_id}/comment",
        data={
            "visibility_scope": "dept_b_internal",
            "body": "Please review this next @teammate@example.com",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200

    with app.app_context():
        mention = Notification.query.filter_by(
            user_id=mentioned_id,
            type="mention",
            request_id=req_id,
        ).first()
        assert mention is not None
        assert "mentioned" in mention.title.lower()


def test_search_filters_support_sla_and_approval_views_and_bulk_priority_update(app, client):
    admin_id = _create_user(app, "search-admin@example.com", department="B", is_admin=True)

    with app.app_context():
        overdue_req = Request(
            title="Overdue widget",
            request_type="part_number",
            description="Past due request",
            priority="low",
            status="NEW_FROM_A",
            owner_department="B",
            submitter_type="user",
            created_by_user_id=admin_id,
            pricebook_status="unknown",
            due_at=datetime.utcnow() - timedelta(days=1),
        )
        approval_req = Request(
            title="Exec approval widget",
            request_type="part_number",
            description="Needs signoff",
            priority="medium",
            status="EXEC_APPROVAL",
            owner_department="B",
            submitter_type="user",
            created_by_user_id=admin_id,
            pricebook_status="unknown",
            due_at=datetime.utcnow() + timedelta(days=7),
        )
        db.session.add_all([overdue_req, approval_req])
        db.session.commit()
        overdue_id = overdue_req.id
        approval_id = approval_req.id

    rv = _login(client, "search-admin@example.com")
    assert rv.status_code == 200

    rv = client.get("/search?sla=breached")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Overdue widget" in html
    assert "SLA breached" in html
    assert "Exec approval widget" not in html

    rv = client.get("/search?approval_only=1")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Exec approval widget" in html
    assert "Approval queue" in html
    assert "Overdue widget" not in html

    rv = client.post(
        "/requests/bulk_update",
        data={
            "request_ids": [str(overdue_id), str(approval_id)],
            "priority": "high",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Updated priority on 2 requests." in rv.data

    with app.app_context():
        overdue_req = db.session.get(Request, overdue_id)
        approval_req = db.session.get(Request, approval_id)
        assert overdue_req.priority == "high"
        assert approval_req.priority == "high"


def test_admin_integration_health_allows_retrying_failed_event(app, client):
    _create_user(app, "ops-admin@example.com", department="B", is_admin=True)

    with app.app_context():
        event = IntegrationEvent(
            event_name="request.updated",
            destination_kind="outbox",
            status="failed",
            last_error="provider timeout",
            created_at=datetime.utcnow(),
        )
        job = JobRecord(
            job_name="deliver_webhook",
            queue_name="integrations",
            status="failed",
            error_text="provider timeout",
            created_at=datetime.utcnow(),
        )
        db.session.add_all([event, job])
        db.session.commit()
        event_id = event.id

    rv = _login(client, "ops-admin@example.com")
    assert rv.status_code == 200

    rv = client.get("/admin/integration_events")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Failed events" in html
    assert "Retry" in html
    assert "Jobs needing attention" in html

    rv = client.post(f"/admin/integration_events/{event_id}/retry", follow_redirects=True)
    assert rv.status_code == 200

    with app.app_context():
        event = db.session.get(IntegrationEvent, event_id)
        assert event.status == "pending"
        assert event.last_error is None
