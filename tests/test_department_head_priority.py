from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import DepartmentEditor
from app.models import Request as ReqModel
from app.models import User


def login(client, email, password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_department_head_can_change_priority(app, client):
    # a department editor with change permission should be able to update a
    # request's priority on its detail page.
    with app.app_context():
        head = User(
            email="head-priority@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        db.session.add(head)
        db.session.commit()
        db.session.add(
            DepartmentEditor(
                user_id=head.id,
                department="B",
                can_edit=False,
                can_view_metrics=False,
                can_change_priority=True,
            )
        )
        # create a simple request belonging to dept B
        req = ReqModel(
            title="Priority test",
            request_type="part_number",
            description="x",
            priority="medium",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=3)),
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id

    rv = login(client, "head-priority@example.com")
    assert rv.status_code == 200

    detail = client.get(f"/requests/{req_id}")
    assert detail.status_code == 200
    assert b"Priority control" in detail.data
    assert b"Update priority" in detail.data
    assert b">Highest<" in detail.data

    # submit priority change
    rv = client.post(
        f"/requests/{req_id}/change_priority",
        data={"priority": "high"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Priority updated" in rv.data

    with app.app_context():
        updated = db.session.get(ReqModel, req_id)
        assert updated.priority == "high"


def test_department_head_without_permission_cannot_change(app, client):
    with app.app_context():
        head = User(
            email="no-change@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        db.session.add(head)
        db.session.commit()
        db.session.add(
            DepartmentEditor(
                user_id=head.id,
                department="B",
                can_edit=False,
                can_view_metrics=True,
                can_change_priority=False,
            )
        )
        req = ReqModel(
            title="Cannot change",
            request_type="part_number",
            description="x",
            priority="medium",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=2)),
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id

    rv = login(client, "no-change@example.com")
    assert rv.status_code == 200

    detail = client.get(f"/requests/{req_id}")
    assert detail.status_code == 200
    assert b"Priority control" not in detail.data
    assert b"Update priority" not in detail.data

    rv = client.post(
        f"/requests/{req_id}/change_priority",
        data={"priority": "high"},
        follow_redirects=False,
    )
    # should be forbidden
    assert rv.status_code == 403
