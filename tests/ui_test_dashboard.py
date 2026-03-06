import pytest

# Module-level skip: this UI test acts as a smoke/integration check and is
# skipped by default to avoid running browser-style checks in CI/dev runs.
pytestmark = pytest.mark.skip(reason="Smoke UI test - skipped by default")
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from datetime import datetime, timedelta

from app.models import User, Request as ReqModel, Artifact


@pytest.fixture()
def app():
    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
    )
    with app.app_context():
        db.create_all()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def b_user(app):
    with app.app_context():
        user = User.query.filter_by(email="b@example.com").first()
        if not user:
            user = User(
                name="Dept B User",
                email="b@example.com",
                department="B",
                password_hash=generate_password_hash("password123", method="pbkdf2:sha256"),
                is_active=True,
            )
            db.session.add(user)
            db.session.commit()
        return user


def _seed_requests(app):
    now = datetime.utcnow()
    with app.app_context():
        db.session.query(Artifact).delete()
        db.session.query(ReqModel).delete()
        db.session.commit()

        def make_req(title, status, artifacts=None):
            req = ReqModel(
                title=title,
                request_type="both",
                pricebook_status="pending",
                description="test",
                priority="medium",
                requires_c_review=True,
                status=status,
                owner_department="B",
                submitter_type="user",
                created_by_user_id=None,
                due_at=now + timedelta(days=3),
            )
            db.session.add(req)
            db.session.flush()
            for art in artifacts or []:
                db.session.add(Artifact(
                    request_id=req.id,
                    artifact_type=art.get("type"),
                    target_part_number=art.get("target"),
                    donor_part_number=art.get("donor"),
                    created_by_department="B",
                ))
            return req

        make_req("In Progress Req", "B_IN_PROGRESS")
        make_req("Method Created Req", "B_IN_PROGRESS", artifacts=[{"type": "instructions"}])
        make_req("Part Number Created Req", "B_IN_PROGRESS", artifacts=[{"type": "part_number", "target": "PN-123"}])
        make_req("Pending C Review Req", "PENDING_C_REVIEW")
        make_req("Final Review Req", "B_FINAL_REVIEW")
        make_req("Closed Req", "CLOSED")
        db.session.commit()


def test_dashboard_filters_render(client, b_user, app):
    _seed_requests(app)

    resp = client.post(
        "/auth/login",
        data={"email": "b@example.com", "password": "password123"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Dashboard" in resp.get_data(as_text=True)

    r = client.get("/dashboard")
    html = r.get_data(as_text=True)
    assert 'id="statusFilter"' in html

    required = [
        ("in_progress", "In progress"),
        ("method_created", "Method created"),
        ("part_number_created", "Part number created"),
        ("under_review_by_department_c", "Under review by Department C"),
        ("under_final_review", "Under final review"),
        ("request_denied", "Request denied"),
    ]
    for val, label in required:
        assert f'value="{val}"' in html or label in html

    r2 = client.get("/dashboard?status=in_progress")
    assert r2.status_code == 200
    assert "In Progress Req" in r2.get_data(as_text=True)

    assert "Method Created Req" in client.get("/dashboard?status=method_created").get_data(as_text=True)
    assert "Part Number Created Req" in client.get("/dashboard?status=part_number_created").get_data(as_text=True)
    assert "Pending C Review Req" in client.get("/dashboard?status=under_review_by_department_c").get_data(as_text=True)
    assert "Final Review Req" in client.get("/dashboard?status=under_final_review").get_data(as_text=True)
    assert "Closed Req" in client.get("/dashboard?status=request_denied").get_data(as_text=True)
