from datetime import datetime, timedelta
from types import SimpleNamespace

from werkzeug.security import generate_password_hash

import app.notifcations as notifications_module
from app.extensions import db
from app.models import Department, DepartmentEditor, Notification, User, UserDepartment
from app.notifcations import notify_users, users_in_department
from app.services.integrations import build_handoff_bundle_payload


def _create_user(app, email, *, department="A", is_admin=False, password="secret"):
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


def test_bulk_role_profile_creates_managed_department_editor(app, client):
    _create_user(app, "workflow-admin@example.com", is_admin=True)
    user_id = _create_user(app, "workflow-user@example.com", department="B")

    rv = _login(client, "workflow-admin@example.com")
    assert rv.status_code == 200

    resp = client.post(
        "/admin/users/bulk_update",
        data={
            "user_ids": [str(user_id)],
            "bulk_action": "apply_role_profile",
            "bulk_role_profile": "queue_lead",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.workflow_role_profile == "queue_lead"
        rows = DepartmentEditor.query.filter_by(user_id=user_id).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.department == "B"
        assert row.managed_by_profile is True
        assert row.can_edit is True
        assert row.can_view_metrics is True
        assert row.can_change_priority is True



def test_temporary_department_assignment_expires_from_available_departments(app, client):
    _create_user(app, "dept-admin@example.com", is_admin=True)
    user_id = _create_user(app, "loaned-user@example.com", department="A")

    _login(client, "dept-admin@example.com")
    resp = client.post(
        f"/admin/users/{user_id}/departments",
        data={
            "departments": ["B"],
            "assignment_kind_B": "temporary",
            "assignment_expires_at_B": (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "assignment_note_B": "Finance handoff coverage",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    client.get("/auth/logout", follow_redirects=True)
    _login(client, "loaned-user@example.com")
    dept_resp = client.get("/auth/departments")
    assert dept_resp.status_code == 200
    assert dept_resp.get_json()["departments"] == ["A", "B"]

    with app.app_context():
        loan = UserDepartment.query.filter_by(user_id=user_id, department="B").first()
        assert loan is not None
        loan.expires_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.add(loan)
        db.session.commit()

    dept_resp = client.get("/auth/departments")
    assert dept_resp.status_code == 200
    assert dept_resp.get_json()["departments"] == ["A"]



def test_preferred_department_landing_and_quick_access_links_render(app, client):
    _create_user(app, "landing-admin@example.com", is_admin=True)
    user_id = _create_user(app, "landing-user@example.com", department="A")

    with app.app_context():
        db.session.add(UserDepartment(user_id=user_id, department="B", assignment_kind="shared"))
        user = db.session.get(User, user_id)
        user.preferred_start_page = "dashboard"
        user.preferred_start_department = "B"
        user.watched_departments = ["A", "B"]
        db.session.add(user)
        db.session.commit()

    rv = _login(client, "landing-user@example.com")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Dept B — Work queue" in html
    assert "Cross-department quick access" in html
    assert "Dept A" in html

    with client.session_transaction() as sess:
        assert sess.get("active_dept") == "B"


def test_notification_routing_and_backup_approver_receive_alerts(app):
    with app.app_context():
        primary = User(
            email="primary-alerts@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
        )
        routed = User(
            email="routed-alerts@example.com",
            password_hash=generate_password_hash("secret"),
            department="C",
            is_active=True,
        )
        borrowed = User(
            email="borrowed-alerts@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        backup = User(
            email="backup-alerts@example.com",
            password_hash=generate_password_hash("secret"),
            department="C",
            is_active=True,
        )
        db.session.add_all([primary, routed, borrowed, backup])
        db.session.commit()

        routed.notification_departments = ["A"]
        primary.backup_approver_user_id = backup.id
        db.session.add(UserDepartment(user_id=borrowed.id, department="A", assignment_kind="shared"))
        db.session.add_all([primary, routed])
        db.session.commit()

        recipients = users_in_department("A")
        assert {user.email for user in recipients} == {
            "primary-alerts@example.com",
            "routed-alerts@example.com",
            "borrowed-alerts@example.com",
            "backup-alerts@example.com",
        } - {"backup-alerts@example.com"}

        notify_users([primary], "Coverage notice", "Backup should receive this too.", allow_email=False)
        db.session.commit()

        primary_note = Notification.query.filter_by(user_id=primary.id).order_by(Notification.id.desc()).first()
        backup_note = Notification.query.filter_by(user_id=backup.id).order_by(Notification.id.desc()).first()
        assert primary_note is not None
        assert backup_note is not None
        assert primary_note.title == "Coverage notice"
        assert backup_note.title == "Coverage notice — backup coverage"
        assert "backup approver for primary-alerts@example.com" in (backup_note.body or "")


def test_admin_can_save_notification_routing_and_backup_approver(app, client):
    admin_id = _create_user(app, "coverage-admin@example.com", is_admin=True, department="B")
    user_id = _create_user(app, "coverage-user@example.com", department="A")
    backup_id = _create_user(app, "coverage-backup@example.com", department="B")

    rv = _login(client, "coverage-admin@example.com")
    assert rv.status_code == 200

    resp = client.post(
        f"/admin/users/{user_id}/edit",
        data={
            "email": "coverage-user@example.com",
            "name": "Coverage User",
            "password": "",
            "role": "user",
            "department": "A",
            "is_active": "y",
            "workflow_role_profile": "coordinator",
            "preferred_start_page": "dashboard",
            "preferred_start_department": "",
            "watched_departments": ["A", "B"],
            "notification_departments": ["B", "C"],
            "backup_approver_user_id": str(backup_id),
            "daily_nudge_limit": "1",
            "quote_interval": "20",
            "quote_set": "",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.notification_departments == ["B", "C"]
        assert user.backup_approver_user_id == backup_id


def test_coverage_calendar_renders_loans_and_backup_pairs(app, client):
    _create_user(app, "calendar-admin@example.com", is_admin=True, department="B")
    user_id = _create_user(app, "calendar-user@example.com", department="A")
    backup_id = _create_user(app, "calendar-backup@example.com", department="C")

    with app.app_context():
        user = db.session.get(User, user_id)
        user.backup_approver_user_id = backup_id
        user.notification_departments = ["B"]
        db.session.add(
            UserDepartment(
                user_id=user_id,
                department="B",
                assignment_kind="temporary",
                note="Quarter-end queue coverage",
                expires_at=datetime.utcnow() + timedelta(days=2),
            )
        )
        db.session.add(user)
        db.session.commit()

    rv = _login(client, "calendar-admin@example.com")
    assert rv.status_code == 200

    resp = client.get("/admin/users/coverage?dept=B&days=7")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Coverage calendar" in html
    assert "Quarter-end queue coverage" in html
    assert "calendar-backup@example.com" in html


def test_dynamic_department_choices_and_handoff_package_render(app, client):
    _create_user(app, "dynamic-admin@example.com", is_admin=True, department="A")
    user_id = _create_user(app, "dynamic-user@example.com", department="A")

    with app.app_context():
        dept = Department(code="X", label="Expansion")
        db.session.add(dept)
        db.session.commit()

    _login(client, "dynamic-admin@example.com")
    page = client.get(f"/admin/users/{user_id}/departments")
    assert page.status_code == 200
    assert "Expansion" in page.get_data(as_text=True)

    resp = client.post(
        f"/admin/users/{user_id}/departments",
        data={
            "departments": ["X"],
            "assignment_kind_X": "temporary",
            "assignment_expires_at_X": (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "assignment_note_X": "Expansion desk handoff",
            "assignment_handoff_doc_url_X": "https://example.com/handoff/x",
            "assignment_handoff_checklist_X": "Review queue\nConfirm owner\nPost update",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        row = UserDepartment.query.filter_by(user_id=user_id, department="X").first()
        assert row is not None
        assert row.handoff_doc_url == "https://example.com/handoff/x"
        assert row.handoff_checklist == ["Review queue", "Confirm owner", "Post update"]

    coverage = client.get("/admin/users/coverage?dept=X&days=7")
    assert coverage.status_code == 200
    html = coverage.get_data(as_text=True)
    assert "Open handoff doc" in html
    assert "Review queue" in html


def test_department_handoff_defaults_apply_when_assignment_fields_blank(app, client):
    _create_user(app, "defaults-admin@example.com", is_admin=True, department="A")
    user_id = _create_user(app, "defaults-user@example.com", department="A")

    with app.app_context():
        dept = Department(code="X", label="Expansion")
        dept.handoff_template_doc_url = "https://example.com/templates/x"
        dept.handoff_template_checklist = ["Review queue", "Confirm owner", "Send recap"]
        db.session.add(dept)
        db.session.commit()

    _login(client, "defaults-admin@example.com")
    page = client.get(f"/admin/users/{user_id}/departments")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "https://example.com/templates/x" in html
    assert "Review queue\nConfirm owner\nSend recap" in html

    resp = client.post(
        f"/admin/users/{user_id}/departments",
        data={
            "departments": ["X"],
            "assignment_kind_X": "temporary",
            "assignment_expires_at_X": (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "assignment_note_X": "Expansion desk handoff",
            "assignment_handoff_doc_url_X": "",
            "assignment_handoff_checklist_X": "",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        row = UserDepartment.query.filter_by(user_id=user_id, department="X").first()
        assert row is not None
        assert row.handoff_doc_url == "https://example.com/templates/x"
        assert row.handoff_checklist == ["Review queue", "Confirm owner", "Send recap"]


def test_coverage_calendar_ics_export_includes_loans(app, client):
    """Downloadable .ics should be produced with VEVENT entries matching loans."""
    _create_user(app, "ics-admin@example.com", is_admin=True, department="B")
    user_id = _create_user(app, "ics-user@example.com", department="A")
    with app.app_context():
        db.session.add(
            UserDepartment(
                user_id=user_id,
                department="B",
                assignment_kind="temporary",
                note="ICS export test",
                expires_at=datetime.utcnow() + timedelta(days=1),
            )
        )
        db.session.commit()

    _login(client, "ics-admin@example.com")
    resp = client.get("/admin/users/coverage?dept=B&days=7&format=ics")
    assert resp.status_code == 200
    assert resp.headers.get("Content-Type").startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in resp.get_data(as_text=True)
    assert "ICS export test" in resp.get_data(as_text=True)


def test_coverage_calendar_search_filters_and_saves_query(app, client):
    _create_user(app, "search-admin@example.com", is_admin=True, department="A")
    first_user_id = _create_user(app, "search-user@example.com", department="A")
    second_user_id = _create_user(app, "other-user@example.com", department="A")

    with app.app_context():
        dept = Department(code="X", label="Expansion Team")
        db.session.add(dept)
        db.session.add(
            UserDepartment(
                user_id=first_user_id,
                department="X",
                assignment_kind="temporary",
                note="Expansion desk handoff",
                expires_at=datetime.utcnow() + timedelta(days=2),
                handoff_checklist_json='["Review queue", "Confirm owner"]',
            )
        )
        db.session.add(
            UserDepartment(
                user_id=second_user_id,
                department="X",
                assignment_kind="temporary",
                note="Finance backlog catchup",
                expires_at=datetime.utcnow() + timedelta(days=2),
                handoff_checklist_json='["Archive docs"]',
            )
        )
        db.session.commit()

    _login(client, "search-admin@example.com")
    filtered = client.get("/admin/users/coverage?dept=X&days=7&q=owner")
    assert filtered.status_code == 200
    html = filtered.get_data(as_text=True)
    assert "Confirm owner" in html
    assert "Expansion desk handoff" in html
    assert "Finance backlog catchup" not in html

    persisted = client.get("/admin/users/coverage")
    assert persisted.status_code == 200
    persisted_html = persisted.get_data(as_text=True)
    assert 'value="owner"' in persisted_html
    assert 'option value="X" selected' in persisted_html
    assert 'option value="7" selected' in persisted_html



def test_department_notification_template_injected(app):
    """Notifications sent to a user honor the department's custom template."""
    with app.app_context():
        # create a custom department entry
        dept = Department(code="Z", label="ZDept")
        dept.notification_template = "[DeptZ] {{ body }}"
        db.session.add(dept)
        db.session.commit()

        user = User(
            email="templated@example.com",
            password_hash=generate_password_hash("secret"),
            department="Z",
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()

        notify_users([user], "Title", "Hi there", allow_email=False)
        db.session.commit()
        note = Notification.query.filter_by(user_id=user.id).first()
        assert note is not None
        assert note.body.startswith("[DeptZ]")
        assert "Hi there" in note.body


def test_notification_fanout_threshold_uses_async_path(app, monkeypatch):
    captured = {}

    with app.app_context():
        app.config["NOTIFICATION_FANOUT_ASYNC_THRESHOLD"] = 1
        user_one = User(
            email="fanout-one@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
        )
        user_two = User(
            email="fanout-two@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
        )
        db.session.add_all([user_one, user_two])
        db.session.commit()

        def fake_send_notification_fanout_async(entries, request_id=None):
            captured["entries"] = entries
            captured["request_id"] = request_id

        monkeypatch.setattr(notifications_module, "_send_notification_fanout_async", fake_send_notification_fanout_async)

        notify_users([user_one, user_two], "Fanout", "Scale path", allow_email=False, request_id=42)

        assert len(captured.get("entries") or []) == 2
        assert captured.get("request_id") == 42
        assert Notification.query.count() == 0


def test_build_handoff_bundle_payload_includes_submission_and_attachments():
    request_obj = SimpleNamespace(
        id=12,
        title="Transfer hardware",
        status="pending",
        owner_department="B",
    )
    submission_obj = SimpleNamespace(
        id=34,
        from_department="A",
        to_department="B",
        from_status="submitted",
        to_status="processing",
        summary="Laptop handoff",
        details="Includes charger and dock.",
        created_at=datetime(2026, 1, 2, 3, 4, 5),
        attachments=[
            SimpleNamespace(
                id=90,
                original_filename="handoff.pdf",
                stored_filename="stored-1.pdf",
                content_type="application/pdf",
                size_bytes=2048,
            )
        ],
    )

    payload = build_handoff_bundle_payload(request_obj, submission_obj)

    assert payload["event"] == "handoff_bundle"
    assert payload["request"]["id"] == 12
    assert payload["request"]["owner_department"] == "B"
    assert payload["submission"]["to_department"] == "B"
    assert payload["submission"]["summary"] == "Laptop handoff"
    assert payload["attachments"] == [
        {
            "id": 90,
            "filename": "handoff.pdf",
            "stored_filename": "stored-1.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
        }
    ]


def test_overlapping_temporary_loans_warn_without_blocking_save(app, client):
    _create_user(app, "overlap-admin@example.com", is_admin=True, department="B")
    user_id = _create_user(app, "overlap-user@example.com", department="A")

    with app.app_context():
        db.session.add(
            UserDepartment(
                user_id=user_id,
                department="B",
                assignment_kind="temporary",
                note="Existing finance coverage",
                expires_at=datetime.utcnow() + timedelta(days=3),
            )
        )
        db.session.commit()

    rv = _login(client, "overlap-admin@example.com")
    assert rv.status_code == 200

    resp = client.post(
        f"/admin/users/{user_id}/departments",
        data={
            "departments": ["B", "C"],
            "assignment_kind_B": "temporary",
            "assignment_expires_at_B": (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"),
            "assignment_note_B": "Existing finance coverage",
            "assignment_kind_C": "temporary",
            "assignment_expires_at_C": (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "assignment_note_C": "Ops support overlap",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Coverage warning" in resp.data

    with app.app_context():
        saved = UserDepartment.query.filter_by(user_id=user_id, department="C").first()
        assert saved is not None
        assert saved.assignment_kind == "temporary"


def test_coverage_calendar_saves_filters_in_session(app, client):
    _create_user(app, "saved-filter-admin@example.com", is_admin=True, department="B")

    rv = _login(client, "saved-filter-admin@example.com")
    assert rv.status_code == 200

    first = client.get("/admin/users/coverage?dept=C&days=7&q=backup")
    assert first.status_code == 200
    second = client.get("/admin/users/coverage")
    assert second.status_code == 200
    html = second.get_data(as_text=True)
    assert 'option value="C" selected' in html
    assert 'option value="7" selected' in html
    assert 'value="backup"' in html
    assert "saved for this session" in html

    reset = client.get("/admin/users/coverage?reset=1")
    assert reset.status_code == 200
    reset_html = reset.get_data(as_text=True)
    assert 'option value="" selected' in reset_html
    assert 'option value="14" selected' in reset_html
