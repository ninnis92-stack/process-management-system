import re

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import FeatureFlags, User


CARD_URL_RE = re.compile(r'data-nav-url="([^"]+)"')


def _login_admin(client, email="admin-logic@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_admin_command_center_cards_route_to_expected_pages(app, client):
    with app.app_context():
        admin = User(
            email="admin-logic@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

    rv = _login_admin(client)
    assert rv.status_code == 200

    rv = client.get("/admin/")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)

    # ensure the page is aware we're an admin; the client-side department
    # picker is suppressed for admins so we don't get annoying prompts on
    # reload (especially noticeable on phones).
    assert 'data-user-is-admin="1"' in html
    # our inline script should also include the early-return check for
    # admin status and for the presence of a navbar department selector.
    # when either condition is true the modal logic returns early.
    assert 'if (!loggedIn || active || isAdmin || navbarDept) return;' in html

    expected_labels = {
        "Users",
        "Departments",
        "Workspace branding",
        "Quotes",
        "Email Forms",
        "Monitoring",
        "Status Options",
        "Process Flows",
        "Buckets",
        "Switch department",
        "Notifications",
        "Notification Retention",
        "Flags & integrations",
        "Migrations",
        "Debug workspace",
        "Tenants",
        "Jobs",
        "Integration Events",
        "Open metrics overview",
        "Explore feature flags",
    }
    for label in expected_labels:
        assert label in html

    assert "First admin pass" in html
    assert "Model the route" in html
    assert "Publish the workspace" in html

    urls = set(CARD_URL_RE.findall(html))
    expected_urls = {
        "/admin/users",
        "/admin/departments",
        "/admin/site_config",
        "/admin/site_config#quotes-settings",
        "/admin/special_email",
        "/admin/monitor",
        "/admin/status_options",
        "/admin/workflows",
        "/admin/buckets",
        "/auth/choose_dept",
        "/admin/notifications_retention",
        "/admin/feature_flags",
        "/admin/migrations/status",
        "/admin/debug_workspace",
        "/admin/tenants",
        "/admin/jobs",
        "/admin/integration_events",
    }
    assert expected_urls.issubset(urls)

    for url in expected_urls:
        route = url.split("#", 1)[0]
        response = client.get(route, follow_redirects=False)
        assert response.status_code in (200, 302), route

    for hero_url in ("/admin/metrics_overview", "/admin/feature_flags"):
        response = client.get(hero_url, follow_redirects=False)
        assert response.status_code in (200, 302), hero_url


def test_admin_navbar_department_switch_updates_session(app, client):
    # Admins should see the navbar dropdown and be able to POST to switch_dept,
    # which persists their active department rather than relying solely on ?as_dept.
    with app.app_context():
        admin = User(
            email="admin-switch@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

    rv = _login_admin(client, email="admin-switch@example.com")
    assert rv.status_code == 200
    page = client.get("/admin/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="navbarDeptSelect"' in html

    # choose a different department via POST
    resp = client.post("/auth/switch_dept", data={"department": "A"}, follow_redirects=True)
    assert resp.status_code == 200
    dash = client.get("/dashboard")
    assert 'data-active-dept="A"' in dash.get_data(as_text=True)


def test_admin_notifications_card_toggles_feature_flag(app, client):
    with app.app_context():
        admin = User(
            email="admin-toggle@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

        flags = FeatureFlags.get()
        flags.enable_notifications = True
        db.session.commit()

    rv = _login_admin(client, email="admin-toggle@example.com")
    assert rv.status_code == 200

    rv = client.post("/admin/toggle_notifications", follow_redirects=True)
    assert rv.status_code == 200
    assert b"Notifications disabled." in rv.data

    with app.app_context():
        flags = FeatureFlags.get()
        assert flags.enable_notifications is False

    rv = client.post("/admin/toggle_notifications", follow_redirects=True)
    assert rv.status_code == 200
    assert b"Notifications enabled." in rv.data

    with app.app_context():
        flags = FeatureFlags.get()
        assert flags.enable_notifications is True


def test_admin_can_hide_onboarding_guidance_panel(app, client):
    with app.app_context():
        admin = User(
            email="admin-no-guide@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
            onboarding_guidance_enabled=False,
        )
        db.session.add(admin)
        db.session.commit()

    rv = _login_admin(client, email="admin-no-guide@example.com")
    assert rv.status_code == 200

    rv = client.get("/admin/")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "First admin pass" not in html
    assert "Workflow signal" not in html


def test_user_settings_surface_expected_controls(app, client):
    with app.app_context():
        user = User(
            email="settings-check@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
        )
        db.session.add(user)
        db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "settings-check@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200

    rv = client.get("/auth/settings")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    for expected in (
        "Theme",
        "Message set",
        "Rotating quotes enabled",
        "Learning aids",
        "Onboarding guidance enabled",
    ):
        assert expected in html
