from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import Request as ReqModel, RequestApproval, StatusOption, Tenant, TenantMembership, User


def login(client, email, password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_admin_can_configure_approval_stages_on_status_options(app, client):
    with app.app_context():
        admin = User(
            email="approval-admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

    rv = login(client, "approval-admin@example.com")
    assert rv.status_code == 200

    rv = client.post(
        "/admin/status_options/new",
        data={
            "code": "EXEC_APPROVAL",
            "label": "Requires executive approval",
            "approval_stages_text": "Executive signoff | tenant_admin | B\nOperations review | analyst | B",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "2 stages" in html
    assert "Executive signoff, Operations review" in html

    with app.app_context():
        opt = StatusOption.query.filter_by(code="EXEC_APPROVAL").first()
        assert opt is not None
        assert opt.approval_stages == [
            {"name": "Executive signoff", "role": "tenant_admin", "department": "B"},
            {"name": "Operations review", "role": "analyst", "department": "B"},
        ]


def test_multi_stage_approval_requires_matching_roles_before_completion(app, client, monkeypatch):
    monkeypatch.setattr("app.requests_bp.routes.emit_webhook_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.requests_bp.routes.record_process_metric_event", lambda *args, **kwargs: None)

    with app.app_context():
        tenant = Tenant.get_default()
        status = StatusOption(code="PENDING_C_REVIEW", label="Pending C Review")
        status.approval_stages = [
            {"name": "C analyst review", "role": "analyst", "department": "C"},
            {"name": "C final signoff", "role": "member", "department": "C"},
        ]
        b_user = User(
            email="approval-b@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        c_analyst = User(
            email="approval-c-analyst@example.com",
            password_hash=generate_password_hash("secret"),
            department="C",
            is_active=True,
        )
        c_member = User(
            email="approval-c-member@example.com",
            password_hash=generate_password_hash("secret"),
            department="C",
            is_active=True,
        )
        db.session.add_all([status, b_user, c_analyst, c_member])
        db.session.flush()
        db.session.add_all(
            [
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=b_user.id,
                    role="member",
                    is_default=True,
                    is_active=True,
                ),
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=c_analyst.id,
                    role="analyst",
                    is_default=True,
                    is_active=True,
                ),
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=c_member.id,
                    role="member",
                    is_default=True,
                    is_active=True,
                ),
            ]
        )
        req = ReqModel(
            title="Needs staged review",
            request_type="both",
            pricebook_status="unknown",
            description="Route this through C approvals",
            priority="medium",
            status="B_IN_PROGRESS",
            owner_department="B",
            requires_c_review=True,
            submitter_type="user",
            created_by_user_id=b_user.id,
            due_at=datetime.utcnow() + timedelta(days=2),
        )
        db.session.add(req)
        db.session.commit()
        request_id = req.id

    rv = login(client, "approval-b@example.com")
    assert rv.status_code == 200
    rv = client.post(
        f"/requests/{request_id}/transition",
        data={
            "to_status": "PENDING_C_REVIEW",
            "requires_c_review": "y",
            "submission_summary": "Sending to Department C for signoff",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200

    with app.app_context():
        req = db.session.get(ReqModel, request_id)
        approvals = (
            RequestApproval.query.filter_by(request_id=request_id, status_code="PENDING_C_REVIEW")
            .order_by(RequestApproval.stage_order.asc())
            .all()
        )
        assert req.status == "PENDING_C_REVIEW"
        assert [approval.stage_name for approval in approvals] == [
            "C analyst review",
            "C final signoff",
        ]
        first_id = approvals[0].id
        second_id = approvals[1].id

    rv = login(client, "approval-c-member@example.com")
    assert rv.status_code == 200
    rv = client.post(
        f"/requests/{request_id}/approvals/{first_id}/decision",
        data={"decision": "approve", "note": "I should not be able to do this"},
        follow_redirects=False,
    )
    assert rv.status_code == 403

    rv = login(client, "approval-c-analyst@example.com")
    assert rv.status_code == 200
    detail = client.get(f"/requests/{request_id}")
    assert detail.status_code == 200
    detail_html = detail.get_data(as_text=True)
    assert "Approval progress" in detail_html
    assert "C analyst review" in detail_html
    assert "C final signoff" in detail_html

    rv = client.post(
        f"/requests/{request_id}/approvals/{first_id}/decision",
        data={"decision": "approve", "note": "Looks good"},
        follow_redirects=True,
    )
    assert rv.status_code == 200

    rv = client.post(
        f"/requests/{request_id}/transition",
        data={"to_status": "C_APPROVED", "submission_summary": "Approved by Department C"},
        follow_redirects=True,
    )
    html = rv.get_data(as_text=True)
    assert "Complete every configured approval stage" in html

    rv = login(client, "approval-c-member@example.com")
    assert rv.status_code == 200
    rv = client.post(
        f"/requests/{request_id}/approvals/{second_id}/decision",
        data={"decision": "approve", "note": "Final signoff complete"},
        follow_redirects=True,
    )
    assert rv.status_code == 200

    rv = client.post(
        f"/requests/{request_id}/transition",
        data={"to_status": "C_APPROVED", "submission_summary": "Approved by Department C"},
        follow_redirects=True,
    )
    assert rv.status_code == 200

    with app.app_context():
        req = db.session.get(ReqModel, request_id)
        approvals = (
            RequestApproval.query.filter_by(request_id=request_id, status_code="PENDING_C_REVIEW")
            .order_by(RequestApproval.stage_order.asc())
            .all()
        )
        assert req.status == "C_APPROVED"
        assert [approval.state for approval in approvals] == ["approved", "approved"]


def test_signoff_history_and_dashboard_cards_show_new_cycles(app, client, monkeypatch):
    monkeypatch.setattr("app.requests_bp.routes.emit_webhook_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.requests_bp.routes.record_process_metric_event", lambda *args, **kwargs: None)

    with app.app_context():
        tenant = Tenant.get_default()
        status = StatusOption(code="PENDING_C_REVIEW", label="Pending C Review")
        status.approval_stages = [
            {"name": "C analyst review", "role": "analyst", "department": "C"},
            {"name": "C final signoff", "role": "member", "department": "C"},
        ]
        b_user = User(
            email="history-b@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        c_analyst = User(
            email="history-c-analyst@example.com",
            password_hash=generate_password_hash("secret"),
            department="C",
            is_active=True,
        )
        c_member = User(
            email="history-c-member@example.com",
            password_hash=generate_password_hash("secret"),
            department="C",
            is_active=True,
        )
        db.session.add_all([status, b_user, c_analyst, c_member])
        db.session.flush()
        db.session.add_all(
            [
                TenantMembership(tenant_id=tenant.id, user_id=b_user.id, role="member", is_default=True, is_active=True),
                TenantMembership(tenant_id=tenant.id, user_id=c_analyst.id, role="analyst", is_default=True, is_active=True),
                TenantMembership(tenant_id=tenant.id, user_id=c_member.id, role="member", is_default=True, is_active=True),
            ]
        )
        req = ReqModel(
            title="History review",
            request_type="both",
            pricebook_status="unknown",
            description="Create multiple approval cycles",
            priority="medium",
            status="B_IN_PROGRESS",
            owner_department="B",
            requires_c_review=True,
            submitter_type="user",
            created_by_user_id=b_user.id,
            due_at=datetime.utcnow() + timedelta(days=2),
        )
        db.session.add(req)
        db.session.commit()
        request_id = req.id

    login(client, "history-b@example.com")
    client.post(
        f"/requests/{request_id}/transition",
        data={
            "to_status": "PENDING_C_REVIEW",
            "requires_c_review": "y",
            "submission_summary": "Cycle one",
        },
        follow_redirects=True,
    )

    with app.app_context():
        approvals = (
            RequestApproval.query.filter_by(request_id=request_id, status_code="PENDING_C_REVIEW")
            .order_by(RequestApproval.stage_order.asc())
            .all()
        )
        first_id = approvals[0].id
        second_id = approvals[1].id

    login(client, "history-c-analyst@example.com")
    client.post(
        f"/requests/{request_id}/approvals/{first_id}/decision",
        data={"decision": "approve", "note": "Cycle one analyst"},
        follow_redirects=True,
    )

    login(client, "history-c-member@example.com")
    client.post(
        f"/requests/{request_id}/approvals/{second_id}/decision",
        data={"decision": "changes_requested", "note": "Need updates"},
        follow_redirects=True,
    )
    client.post(
        f"/requests/{request_id}/transition",
        data={"to_status": "C_NEEDS_CHANGES", "submission_summary": "Need updates from Department B"},
        follow_redirects=True,
    )

    login(client, "history-b@example.com")
    client.post(
        f"/requests/{request_id}/transition",
        data={"to_status": "B_IN_PROGRESS", "submission_summary": "Back to B"},
        follow_redirects=True,
    )
    client.post(
        f"/requests/{request_id}/transition",
        data={
            "to_status": "PENDING_C_REVIEW",
            "requires_c_review": "y",
            "submission_summary": "Cycle two",
        },
        follow_redirects=True,
    )

    rv = login(client, "history-c-analyst@example.com")
    assert rv.status_code == 200
    detail = client.get(f"/requests/{request_id}")
    html = detail.get_data(as_text=True)
    assert "Multi-step signoff history" in html
    assert "Cycle 1" in html
    assert "C analyst review" in html

    dashboard = client.get("/dashboard")
    dashboard_html = dashboard.get_data(as_text=True)
    assert "Needs my signoff" in dashboard_html
    assert "Ready for next step" in dashboard_html
