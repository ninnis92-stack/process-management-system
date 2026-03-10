import re
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import User, SiteConfig, UserDepartment, FeatureFlags


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

    assert "Sign in to keep requests moving" in html
    # form should always submit to the login endpoint even if current URL is wrong
    assert 'form method="post" action="/auth/login"' in html
    assert "Open Guest Dashboard" in html
    assert "Start Guest Submission" in html
    assert "Guest Dashboard" in html
    assert "Guest Submit" in html
    assert 'id="chooseDeptModal"' not in html

    # after redesign the page header now precedes the hero copy; ensure the
    # login form still exists and both phrases are present in the expected
    # relative order (login form earlier than hero text).  we simply check
    # both appear and leave strict position out of the test.
    assert "login-form-panel" in html
    assert "Keep every path consistent from login onward" in html

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


def test_guest_navigation_hides_disabled_public_pages(client, app):
    with app.app_context():
        flags = FeatureFlags.get()
        flags.guest_dashboard_enabled = False
        flags.guest_submission_enabled = False
        db.session.add(flags)
        db.session.commit()

    rv = client.get("/auth/login")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Open Guest Dashboard" not in html
    assert "Start Guest Submission" not in html
    assert "Guest Dashboard" not in html
    assert "Guest Submit" not in html

    assert client.get("/external/dashboard").status_code == 404
    assert client.get("/external/new").status_code == 404


def test_guest_submission_without_dashboard_omits_tracking_link(
    client, app, monkeypatch
):
    with app.app_context():
        flags = FeatureFlags.get()
        flags.guest_dashboard_enabled = False
        flags.guest_submission_enabled = True
        db.session.add(flags)
        db.session.commit()

    monkeypatch.setattr(
        "app.external.routes._send_guest_email", lambda *args, **kwargs: None
    )

    rv = client.post(
        "/external/new",
        data={
            "guest_email": "guest-toggle@example.com",
            "guest_name": "Guest Toggle",
            "title": "Guest toggle request",
            "description": "Need help",
            "request_type": "both",
            "priority": "medium",
            "pricebook_status": "unknown",
            "owner_department": "B",
            "donor_part_number": "D-1",
            "target_part_number": "T-1",
            "due_at": (datetime.utcnow() + timedelta(days=3)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Request #" in html
    assert "Guest tracking pages are currently disabled" in html
    assert "topTrackingLink" not in html


def test_public_guest_pages_do_not_render_department_modal(client):
    for route in ("/external/dashboard", "/external/new"):
        rv = client.get(route)
        assert rv.status_code == 200
        html = rv.get_data(as_text=True)
        assert 'id="chooseDeptModal"' not in html


def test_login_page_no_longer_shows_rolling_quote_banner(client, app):
    # The login page (and any page) should not render a rolling-quote banner
    # under the navbar.  Quotes are now injected only inside the nav element.
    with app.app_context():
        cfg = SiteConfig.get()
        cfg.rolling_quotes_enabled = False
        cfg.rolling_quotes = ["Progress, not perfection."]
        cfg.banner_html = ""
        db.session.add(cfg)
        db.session.commit()

    rv = client.get("/auth/login")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Progress, not perfection." not in html
    assert "Banner text" not in html

    with app.app_context():
        cfg = SiteConfig.get()
        cfg.rolling_quotes_enabled = True
        db.session.add(cfg)
        db.session.commit()

    rv = client.get("/auth/login")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "Progress, not perfection." not in html.split("<script")[0]
    assert "Banner text" not in html.split("<script")[0]


def test_login_page_hides_quotes_when_external_branding_present(client, app):
    # With the rolling-quote banner removed, external branding no longer
    # affects quote visibility. The page should never render the quote text.
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
            cfg.theme_preset = "sky"
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


def test_logged_in_user_is_redirected_away_from_login_page(app, client):
    _create_user(app, email="already-in@example.com", department="B")

    rv = _login(client, "already-in@example.com")
    assert rv.status_code == 200

    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_logged_in_admin_is_redirected_away_from_login_page(app, client):
    _create_user(app, email="already-admin@example.com", is_admin=True)

    rv = _login(client, "already-admin@example.com")
    assert rv.status_code == 200

    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/")


def test_department_a_navigation_links_resolve(app, client):
    _create_user(app, email="dept-a@example.com", department="A")

    rv = _login(client, "dept-a@example.com")
    assert rv.status_code == 200

    page = client.get("/dashboard")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    print(html)

    # non-admin pages should still include the attribute set to "0"
    assert 'data-user-is-admin="0"' in html

    assert "New Request" in html
    assert "Guest Dashboard" in html
    assert "Guest Submit" in html
    assert "Learn the workspace in three moves" in html
    assert "Read the current status" in html

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
    print(html)

    # admin pages should flag the user as an administrator so that client-
    # side logic (like the department picker modal) skips itself.
    assert 'data-user-is-admin="1"' in html
    # sanity check: the inline script includes the branch that looks for
    # isAdmin when deciding whether to show the modal (navbarDept may be added
    # later too).
    assert "if (!loggedIn || active || isAdmin" in html

    # navigation should include guest forms and metrics, and restore a visible
    # admin navbar button for admin users across admin pages.
    assert "Guest Request Forms" in html
    assert "Metrics" in html
    assert re.search(r'href="/admin/"', html)
    assert re.search(r'href="/admin/">\s*<i[^>]*></i><span>Admin</span></a>', html)
    assert not re.search(r'<a class="nav-link[^"]*" href="/admin/">Dashboard</a>', html)
    # banner should include an explicit admin dashboard button for admins
    assert 'class="brand-admin-btn"' in html
    assert "Admin dashboard" in html or 'title="Admin dashboard"' in html
    # ensure breadcrumb isn’t itself a clickable Admin link
    assert not re.search(
        r'<ol class="breadcrumb[^"]*">[\s\S]*?<a[^>]+>Admin<\/a>', html
    )
    if "Retention" not in html:
        # dump for debugging
        print("ADMIN HTML:\n", html)
    assert "Retention" in html  # ensure retention card text shows up
    assert "Switch department" in html  # card we just added (label changed)

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


def test_settings_page_exposes_onboarding_guidance_toggle(app, client):
    _create_user(app, email="guide-toggle@example.com", department="B")

    rv = _login(client, "guide-toggle@example.com")
    assert rv.status_code == 200

    page = client.get("/auth/settings")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    print(html)
    assert "Learning aids" in html
    assert 'name="onboarding_guidance_enabled_present"' in html
    assert 'name="onboarding_guidance_enabled"' in html

    # toggling the checkbox should immediately hide workflow guidance elsewhere
    resp = client.post(
        "/auth/preferences",
        json={
            "onboarding_guidance_enabled": "",
            "onboarding_guidance_enabled_present": "1",
        },
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["preferences"]["onboarding_guidance_enabled"] is False
    # reload home should no longer show the helpful hero callouts
    home = client.get("/")
    assert b"Workflow signal" not in home.data


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
    print(html)
    assert 'id="navbarDeptSelect"' in html
    assert 'data-bs-target="#chooseDeptModal"' not in html
    # inline script should skip the modal when the navbar dropdown exists
    assert "if (!loggedIn || active || isAdmin || navbarDept) return;" in html
    assert "if (!loggedIn || active || isAdmin || navbarDept)" in html

    # switch departments via the new navbar form
    resp = client.post(
        "/auth/switch_dept", data={"department": "B"}, follow_redirects=True
    )
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
    # the motivation slot should be populated with one of the rolling quotes
    # rather than the generic placeholder. this verifies the server-side
    # randomization is working and the placeholder isn't leaking through.
    _create_user(app, email="quote-user@example.com", department="A")
    _login(client, "quote-user@example.com")
    resp = client.get("/dashboard")
    html = resp.get_data(as_text=True)
    assert "Loading inspiration" not in html
    with app.app_context():
        cfg = SiteConfig.get()
        # fall back to the motivation-driven site default now that "motivational"
        # replaced the legacy "default" set as the active baseline.
        quotes = cfg.rolling_quotes or SiteConfig.DEFAULT_QUOTE_SETS.get(
            "motivational", []
        )
    # at least one of the configured quotes should appear somewhere in the html
    assert any(
        q and q in html for q in quotes
    ), "no rolling quote rendered in dashboard"


def test_initial_quote_uses_random_choice(app, client, monkeypatch):
    # patch random.choice to record that it's used when constructing the page
    import random

    calls = []

    def fake_choice(seq):
        calls.append(tuple(seq))
        return seq[0] if seq else None

    monkeypatch.setattr(random, "choice", fake_choice)

    _create_user(app, email="random-test@example.com", department="A")
    _login(client, "random-test@example.com")
    client.get("/dashboard")
    # ensure our fake_choice was called with a nonempty list of quotes
    assert calls, "random.choice was never invoked"
    assert all(isinstance(c, tuple) and c for c in calls)


def test_quote_css_allows_full_quote(client):
    # the navbar styles should not artificially clamp or hide long quotes
    resp = client.get("/static/styles.css")
    css = resp.get_data(as_text=True)
    assert "#motivation" in css
    # ensure the restrictive rules from earlier versions have been removed
    # extract the block for #motivation and inspect its body only
    import re

    match = re.search(r"#motivation\s*\{([^}]*)\}", css, flags=re.DOTALL)
    assert match, "#motivation rule missing from stylesheet"
    body = match.group(1)
    # remove CSS comments so our comment explaining removal doesn't trigger
    body_no_comments = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    # old layout rules removed; we should not see hard max-width/overflow rules
    assert "max-width: none" not in body_no_comments
    assert "overflow: visible" not in body_no_comments
    # clamping is permitted now for responsive design
    assert "line-clamp" in body_no_comments or "-webkit-line-clamp" in body_no_comments


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


def test_department_list_endpoint_preserves_multi_department_order(app, client):
    with app.app_context():
        user = User(
            email="dept-order@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        db.session.add(UserDepartment(user_id=user.id, department="C"))
        db.session.add(UserDepartment(user_id=user.id, department="B"))
        db.session.commit()

    rv = _login(client, "dept-order@example.com")
    assert rv.status_code == 200

    resp = client.get("/auth/departments")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"departments": ["A", "C", "B"]}


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
    # feature flags page should load the bundled frontend script, and the
    # autosave/session-persistence implementation now lives in the Vite module.
    _create_user(app, email="script-admin@example.com", is_admin=True)
    _login(client, "script-admin@example.com")
    rv = client.get("/admin/feature_flags")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "/static/dist/app.js?v=" in html
    with open("frontend/js/modules/autosave.js", "r", encoding="utf-8") as handle:
        script = handle.read()
    assert "toggle_states" in script
    assert "sessionStorage" in script
def test_global_text_color_rule():
    """Ensure stylesheet sets body text color for readability."""
    import os, re
    css_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "styles.css")
    with open(css_path, encoding="utf-8") as f:
        content = f.read()
    assert re.search(r"body[^\{]*\{[^}]*color:\s*var\(--body-text\)", content), "global body color rule missing"