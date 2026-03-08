import re

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import User, SiteConfig, UserDepartment


NAV_LINK_RE = re.compile(r'href="([^"]+)"')


def _extract_nav_links(html):
    links = set()
    for href in NAV_LINK_RE.findall(html):
        if not href.startswith("/"):
            continue
        if href.startswith("/static/"):
            continue
        links.add(href)
    return sorted(links)


def _create_user(app, *, email, password="secret", department="B", is_admin=False):
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


def _login(client, email, password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_public_navigation_links_resolve(client):
    rv = client.get("/auth/login")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)

    assert "Guest Dashboard" in html
    assert "Guest Submit" in html

    links = _extract_nav_links(html)
    expected = {
        "/auth/login",
        "/dashboard",
        "/external/dashboard",
        "/external/new",
    }
    assert expected.issubset(set(links))

    for route in expected:
        resp = client.get(route, follow_redirects=False)
        assert resp.status_code in (200, 302), route
        location = resp.headers.get("Location", "")
        assert not location.endswith("/static/app.js"), route


def test_login_page_always_shows_motivational_quotes(client, app):
    # The login page should follow the rolling quotes toggle: when the
    # flag is disabled no quote renders, but enabling it restores the
    # built-in motivational set so unauthenticated visitors still see a
    # friendly message without needing a user account.
    with app.app_context():
        cfg = SiteConfig.get()
        cfg.rolling_quotes_enabled = False
        cfg.rolling_quotes = []
        cfg.banner_html = '<div>banner</div>'
        db.session.add(cfg)
        db.session.commit()

    rv = client.get("/auth/login")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)

    assert "Progress, not perfection." not in html

    with app.app_context():
        cfg = SiteConfig.get()
        cfg.rolling_quotes_enabled = True
        db.session.add(cfg)
        db.session.commit()

    rv = client.get("/auth/login")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Progress, not perfection." in html


def test_login_page_hides_quotes_when_external_branding_present(client, app):
    with app.app_context():
        cfg = SiteConfig.get()
        orig_banner = cfg.banner_html
        orig_logo = cfg.logo_filename
        orig_theme = cfg.theme_preset
        orig_quotes = list(cfg.rolling_quotes or [])
        orig_flag = cfg.rolling_quotes_enabled
        try:
            cfg.banner_html = "<div>imported banner</div>"
            cfg.logo_filename = "brand/logo.png"
            cfg.theme_preset = "ocean"
            cfg.rolling_quotes_enabled = True
            cfg.rolling_quotes = ["Progress, not perfection."]
            db.session.add(cfg)
            db.session.commit()

            rv = client.get("/auth/login")
            assert rv.status_code == 200
            html = rv.get_data(as_text=True)
            assert "Progress, not perfection." not in html
        finally:
            cfg.banner_html = orig_banner
            cfg.logo_filename = orig_logo
            cfg.theme_preset = orig_theme
            cfg.rolling_quotes = list(orig_quotes)
            cfg.rolling_quotes_enabled = orig_flag
            db.session.add(cfg)
            db.session.commit()


def test_local_test_config_uses_non_secure_session_cookie(app):
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_department_a_navigation_links_resolve(app, client):
    _create_user(app, email="dept-a@example.com", department="A")

    rv = _login(client, "dept-a@example.com")
    assert rv.status_code == 200

    page = client.get("/dashboard")
    assert page.status_code == 200
    html = page.get_data(as_text=True)

    # non-admin pages should still include the attribute set to "0"
    assert 'data-user-is-admin="0"' in html

    assert "New Request" in html
    assert "Guest Dashboard" in html
    assert "Guest Submit" in html

    links = _extract_nav_links(html)
    expected = {
        "/dashboard",
        "/requests/new",
        "/external/dashboard",
        "/external/new",
        "/auth/settings",
    }
    assert expected.issubset(set(links))

    for route in expected:
        resp = client.get(route, follow_redirects=False)
        assert resp.status_code in (200, 302), route
        location = resp.headers.get("Location", "")
        assert not location.endswith("/static/app.js"), route


def test_admin_navigation_links_resolve(app, client):
    _create_user(app, email="nav-admin@example.com", is_admin=True)

    rv = _login(client, "nav-admin@example.com")
    assert rv.status_code == 200
    # login should land on the command center rather than the department picker
    body = rv.get_data(as_text=True)
    assert "Command center" in body

    page = client.get("/admin/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)

    # admin pages should flag the user as an administrator so that client-
    # side logic (like the department picker modal) skips itself.
    assert 'data-user-is-admin="1"' in html
    # sanity check: the inline script includes the branch that looks for
    # isAdmin when deciding whether to show the modal (navbarDept may be added
    # later too).
    assert 'if (!loggedIn || active || isAdmin' in html

    assert "Admin" in html
    assert "Guest Forms" in html
    assert "Metrics" in html
    assert "Retention" in html  # ensure retention card text shows up
    assert "Switch Dept" in html  # card we just added

    links = _extract_nav_links(html)
    expected = {
        "/admin/",
        "/admin/guest_forms",
        "/admin/metrics_config",
        "/admin/notifications_retention",
        "/auth/choose_dept",
        "/external/dashboard",
        "/external/new",
        "/auth/settings",
    }
    assert expected.issubset(set(links))

    for route in expected:
        resp = client.get(route, follow_redirects=False)
        assert resp.status_code in (200, 302), route
        location = resp.headers.get("Location", "")
        assert not location.endswith("/static/app.js"), route


def test_navbar_department_dropdown_for_multi_dept_user(app, client):
    # users assigned to more than one department should see a dropdown in the
    # navbar (same for admins) rather than the modal chooser that pops up on
    # reload.  ensure the dropdown is rendered, the modal link is removed, and
    # switching via POST updates session state.  also verify login does not
    # reroute to /auth/choose_dept when a navbar switcher exists.
    with app.app_context():
        user = User(
            email="multidept@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        ud = UserDepartment(user_id=user.id, department="B")
        db.session.add(ud)
        db.session.commit()

    rv = _login(client, "multidept@example.com")
    assert rv.status_code == 200

    page = client.get("/dashboard")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="navbarDeptSelect"' in html
    assert 'data-bs-target="#chooseDeptModal"' not in html
    # inline script should skip the modal when the navbar dropdown exists
    assert 'if (!loggedIn || active || isAdmin || navbarDept) return;' in html
    assert 'if (!loggedIn || active || isAdmin || navbarDept)' in html

    # switch departments via the new navbar form
    resp = client.post("/auth/switch_dept", data={"department": "B"}, follow_redirects=True)
    assert resp.status_code == 200
    page2 = client.get("/dashboard")
    assert 'data-active-dept="B"' in page2.get_data(as_text=True)

    # logging in again should not redirect to choose_dept page
    rv2 = _login(client, "multidept@example.com")
    assert rv2.status_code == 200
    # since we follow redirects the Location header may be empty; just inspect
    # the body for the chooser text.
    assert b"Select Department" not in rv2.data


def test_initial_quote_on_dashboard(app, client):
    # the motivation slot should be populated with a real quote (at least the
    # first built-in line) rather than the generic placeholder. this ensures the
    # server-side fallback is wired up properly.
    _create_user(app, email="quote-user@example.com", department="A")
    _login(client, "quote-user@example.com")
    resp = client.get("/dashboard")
    html = resp.get_data(as_text=True)
    assert "Loading inspiration" not in html
    # check for a known fragment from the default set
    assert "Sort today" in html


def test_brand_link_respects_company_url(app, client):
    # when site config has a company_url, the navbar-brand href should use it
    with app.app_context():
        cfg = SiteConfig.get()
        cfg.company_url = "https://example.com"
        db.session.add(cfg)
        db.session.commit()
    _create_user(app, email="brand-user@example.com", department="A")
    _login(client, "brand-user@example.com")
    resp = client.get("/dashboard")
    html = resp.get_data(as_text=True)
    assert 'href="https://example.com"' in html
    assert 'target="_blank"' in html


def test_department_list_endpoint(app, client):
    # verify the JSON helper returns correct department lists for users
    _create_user(app, email="dept-json@example.com", department="A")
    _login(client, "dept-json@example.com")
    resp = client.get("/auth/departments")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("departments") == ["A"]

    # admin should see all active departments (at least one, usually more)
    _create_user(app, email="json-admin@example.com", is_admin=True)
    _login(client, "json-admin@example.com")
    resp = client.get("/auth/departments")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and isinstance(data.get("departments"), list)
    assert len(data.get("departments")) >= 1


def test_hero_dashboard_button_targets_match_view_context(app, client):
    guest_page = client.get("/external/dashboard")
    assert guest_page.status_code == 200
    guest_html = guest_page.get_data(as_text=True)
    assert 'data-hero-toggle="dashboard"' in guest_html
    assert 'data-state-open-label="Open guest dashboard"' in guest_html
    assert 'data-state-close-label="Close guest dashboard"' in guest_html
    assert 'data-state-open-url="/external/dashboard"' in guest_html
    assert 'data-state-close-url="/external/new"' in guest_html

    _create_user(app, email="hero-staff@example.com", department="B")
    login_response = _login(client, "hero-staff@example.com")
    assert login_response.status_code == 200

    staff_page = client.get("/dashboard")
    assert staff_page.status_code == 200
    staff_html = staff_page.get_data(as_text=True)
    assert 'data-hero-toggle="dashboard"' in staff_html
    assert 'data-state-open-label="Open staff dashboard"' in staff_html
    assert 'data-state-close-label="Close staff dashboard"' in staff_html
    assert 'data-state-open-url="/dashboard"' in staff_html
    assert 'data-state-close-url="/admin/"' in staff_html


def test_toggle_persistence_script_present(client, app):
    # feature flags page should include our session-storage persistence logic
    _create_user(app, email="script-admin@example.com", is_admin=True)
    _login(client, "script-admin@example.com")
    rv = client.get("/admin/feature_flags")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert 'toggle_states' in html  # key used by script
    assert 'sessionStorage' in html  # ensure storage logic is included
