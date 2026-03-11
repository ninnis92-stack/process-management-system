import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import StatusOption, User, Workflow


def login_admin(client, email="admin@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def make_admin(app):
    with app.app_context():
        # ensure we have a admin user in db
        u = User.query.filter_by(email="admin@example.com").first()
        if not u:
            u = User(
                email="admin@example.com",
                password_hash=generate_password_hash("secret"),
                department="B",
                is_active=True,
                is_admin=True,
            )
            db.session.add(u)
            db.session.commit()
        else:
            u.is_admin = True
            db.session.commit()
        return u


def test_admin_index_links(client, app):
    make_admin(app)
    rv = login_admin(client)
    assert rv.status_code == 200

    rv = client.get("/admin/")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    # both tiles should be present
    assert "/admin/status_options" in html
    assert "/admin/workflows" in html
    assert "Status Options" in html
    assert "Process Flows" in html
    assert "First admin pass" in html
    assert "Start with process flows" in html
    # FontAwesome stylesheet
    assert "font-awesome" in html or "fa-" in html
    # offcanvas toggle button appears for mobile sidebar
    assert 'data-bs-toggle="offcanvas"' in html

    # visit special email configuration and check that nudge select lists small intervals
    rv = client.get("/admin/special_email")
    assert rv.status_code == 200
    spechtml = rv.get_data(as_text=True)
    assert "30 minutes" in spechtml or "0.5" in spechtml
    assert "1 hour" in spechtml


def test_status_options_auto_generated_from_workflows(client, app):
    make_admin(app)
    # ensure clean state
    with app.app_context():
        StatusOption.query.delete()
        Workflow.query.delete()
        db.session.commit()
        # create workflow row with simple steps
        wf = Workflow(
            name="AutoTest",
            spec={
                "steps": ["A_STEP", "B_STEP"],
                "transitions": [{"from": "A_STEP", "to": "B_STEP"}],
            },
            active=True,
        )
        db.session.add(wf)
        db.session.commit()

    # login and visit status options page
    rv = login_admin(client)
    assert rv.status_code == 200
    rv = client.get("/admin/status_options")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    # after page load, we should see the flash message and the two codes
    assert "generated from existing workflows" in html.lower()
    assert "a_step" in html.lower()
    assert "b_step" in html.lower()
    # breadcrumb should indicate where we are
    assert "admin" in html.lower()
    assert "status options" in html.lower()
    # sidebar should be present with a link to process flows
    assert 'class="admin-sidebar"' in html
    assert "/admin/workflows" in html
    # table should be compact, responsive, and well-structured
    assert "table-responsive" in html
    assert "table-sm" in html
    assert "admin-status-table" in html
    # ensure not forcing a horizontal scrollbar by enabling wrapping for actions column
    assert "actions-cell" in html  # class should appear on the last column cell
    # the database should now have entries
    with app.app_context():
        assert StatusOption.query.filter_by(code="A_STEP").first() is not None
        assert StatusOption.query.filter_by(code="B_STEP").first() is not None


def test_workflow_editor_shows_compact_guidance_and_live_preview(client, app):
    make_admin(app)
    rv = login_admin(client)
    assert rv.status_code == 200

    rv = client.get("/admin/workflows/new")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Quick guide" in html
    assert 'id="workflowRoutePreview"' in html
    assert "Submitters only see the next valid route for their department" in html
    assert "Progressive setup" in html
    assert "Terminology guide" in html
    assert "Process flow" in html
    assert 'id="workflowVisualMap"' in html
    assert "Live path map" in html
