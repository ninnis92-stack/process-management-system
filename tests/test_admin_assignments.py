import pytest
from werkzeug.security import generate_password_hash
from app.models import FormTemplate, DepartmentFormAssignment, User, UserDepartment
from app.extensions import db


def login_admin(client, email="admin-assign@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_department_assignment_crud(app, client):
    # Create an admin user and a template
    with app.app_context():
        admin = User(
            email="admin-assign@example.com",
            name="Admin Assign",
            password_hash=generate_password_hash("secret"),
            is_admin=True,
            is_active=True,
            department="B",
        )
        db.session.add(admin)
        t = FormTemplate(name="Dept B Template", description="Template for dept B")
        db.session.add(t)
        db.session.commit()
        template_id = t.id

    # login as admin
    rv = login_admin(client)
    assert b"Logout" in rv.data or rv.status_code == 200

    # assign template to Dept B
    rv = client.post(
        "/admin/assignments/new",
        data={"department": "B", "template_id": str(template_id)},
        follow_redirects=True,
    )
    assert b"Template assigned to department" in rv.data

    # verify assignment exists in DB
    with app.app_context():
        a = DepartmentFormAssignment.query.filter_by(department_name="B").first()
        assert a is not None
        assert a.template_id == template_id

    # list view should show the template name
    rv = client.get("/admin/assignments")
    assert b"Dept B Template" in rv.data

    # delete assignment
    with app.app_context():
        a = DepartmentFormAssignment.query.filter_by(department_name="B").first()
        assert a is not None
        aid = a.id
    rv = client.post(f"/admin/assignments/{aid}/delete", follow_redirects=True)
    assert b"Assignment removed" in rv.data
    with app.app_context():
        assert db.session.get(DepartmentFormAssignment, aid) is None


def test_bulk_assign_departments_deduplicates_and_reports_results(app, client):
    with app.app_context():
        admin = User(
            email="admin-bulk-assign@example.com",
            name="Admin Bulk Assign",
            password_hash=generate_password_hash("secret"),
            is_admin=True,
            is_active=True,
            department="B",
        )
        user = User(
            email="person@example.com",
            name="Person",
            password_hash=generate_password_hash("secret"),
            is_active=True,
            department="A",
        )
        db.session.add_all([admin, user])
        db.session.commit()

    rv = login_admin(client, email="admin-bulk-assign@example.com")
    assert rv.status_code == 200

    rv = client.post(
        "/admin/bulk_assign_departments",
        data={
            "department": "B",
            "emails": "person@example.com\nperson@example.com\nmissing@example.com",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Processed 2 unique emails" in rv.data
    assert b"person@example.com" in rv.data
    assert b"missing@example.com" in rv.data

    with app.app_context():
        assignments = UserDepartment.query.filter_by(department="B").all()
        assert len(assignments) == 1
        assert assignments[0].user_id == user.id
