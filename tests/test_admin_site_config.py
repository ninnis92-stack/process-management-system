import re
import json
import pytest
from app.extensions import db
from app.models import User, Department, SiteConfig
from config import Config
from werkzeug.security import generate_password_hash


def login_admin(client, email="admin@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )



def test_config_validation():
    """Config.validate should catch missing/invalid settings."""
    # run the validator against default class, which will have insecure defaults
    errors = Config.validate()
    # at least the secret key warning should appear
    assert any("SECRET_KEY" in e for e in errors)
    # enabling email without SMTP_HOST should also trigger if we flip flag
    class Dummy(Config):
        EMAIL_ENABLED = True
        SMTP_HOST = ""
        SMTP_PORT = None
    errs2 = Dummy.validate()
    assert any("SMTP_HOST" in e for e in errs2)


def test_departments_crud_and_site_config(app, client):
    with app.app_context():
        # create admin user
        u = User(
            email="admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(u)
        db.session.commit()

    # login as admin
    rv = login_admin(client)
    assert rv.status_code == 200

    # admin index shows the email forms tile (legacy labels removed)
    rv = client.get("/admin/")
    assert rv.status_code == 200
    assert b"Email Forms" in rv.data

    # departments list (empty)
    rv = client.get("/admin/departments")
    assert rv.status_code == 200

    # user list should show workspace column now that multi‑tenant is enabled
    rv = client.get("/admin/users")
    assert rv.status_code == 200
    assert b"Workspace" in rv.data

    # create new department
    rv = client.post(
        "/admin/departments/new",
        data={"code": "X", "name": "Dept X", "order": "10", "active": "y"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Department created" in rv.data

    # verify created in DB
    with app.app_context():
        d = Department.query.filter_by(code="X").first()
        assert d is not None
        did = d.id

    # edit department
    rv = client.post(
        f"/admin/departments/{did}/edit",
        data={"code": "X", "name": "Dept X Updated", "order": "11", "active": ""},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Department updated" in rv.data

    with app.app_context():
        d = db.session.get(Department, did)
        assert d.name == "Dept X Updated"
        assert d.order == 11

    # delete department
    rv = client.post(f"/admin/departments/{did}/delete", follow_redirects=True)
    assert rv.status_code in (200, 302)
    # endpoint returns json OK on success
    assert b'"ok":' in rv.data or rv.status_code == 302

    # Site config GET
    rv = client.get("/admin/site_config")
    assert rv.status_code == 200
    # page should include the quotes-settings anchor for direct linking
    assert b'id="quotes-settings"' in rv.data

    # ensure admin index tile links include anchor (no redirect necessary)
    rv = client.get("/admin/")
    assert rv.status_code == 200
    assert b"#quotes-settings" in rv.data

    # Save site config with banner and rolling quotes
    post_data = {
        "brand_name": "Acme Flow",
        "theme_preset": "forest",
        "banner_html": '<div class="site-banner">Welcome</div>',
        "rolling_enabled": "y",
        "rolling_csv": "Quote one\nQuote two",
    }
    rv = client.post("/admin/site_config", data=post_data, follow_redirects=True)
    assert rv.status_code == 200
    assert b"Site configuration saved" in rv.data

    # Confirm site config persisted and visible in dashboard
    with app.app_context():
        cfg = SiteConfig.get()
        assert cfg.brand_name == "Acme Flow"
        assert cfg.theme_preset == "forest"
        assert cfg.banner_html is not None
        assert cfg.rolling_quotes_enabled is True
        assert isinstance(cfg.rolling_quotes, list)

        # verify that an audit record was created for the configuration change
        from app.models import AuditLog

        recent = (
            AuditLog.query.filter_by(action_type="site_config_update")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert recent is not None
        assert recent.actor_type == "user"
        assert recent.actor_label == "admin@example.com"

        # DEFAULT_QUOTE_SETS uses a uniform length of 30 quotes for every
        # built-in set.  This makes the UI predictable and ensures sufficient
        # rotation while giving admins freedom to replace values.
        defaults = SiteConfig.DEFAULT_QUOTE_SETS
        for name, quotes in defaults.items():
            assert isinstance(quotes, list)
            assert len(quotes) == 30, f"{name} should have exactly 30 quotes"

# Dashboard should include the brand name; banner rendering was removed
        rv = client.get("/dashboard")
        assert rv.status_code == 200
        assert b"Acme Flow" in rv.data


def test_department_quote_permission(app, client):
    # admin can restrict quote sets by department code
    with app.app_context():
        admin = User(
            email="dept-admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=True,
        )
        uA = User(
            email="deptA@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
        )
        uB = User(
            email="deptB@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=False,
        )
        db.session.add_all([admin, uA, uB])
        db.session.commit()
        cfg = SiteConfig.get()
        db.session.commit()
    # admin restricts A to engineering only
    rv = client.post(
        "/auth/login",
        data={"email": "dept-admin@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    restriction = '{"A": ["engineering"]}'
    rv = client.post(
        "/admin/site_config",
        data={"quote_permissions_dept": restriction},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    client.get("/auth/logout")
    # user in A should only see engineering and can't pick others
    rv = client.post(
        "/auth/login",
        data={"email": "deptA@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/auth/settings")
    assert b"engineering" in rv.data
    assert b"productivity" not in rv.data
    client.get("/auth/logout")
    # user in B unaffected by restriction
    rv = client.post(
        "/auth/login",
        data={"email": "deptB@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/auth/settings")
    assert b"engineering" in rv.data
    assert b"productivity" in rv.data


def test_user_quote_permission_overrides_department_and_admin_sees_all_sets(app, client):
    with app.app_context():
        admin = User(
            email="quotes-admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=True,
        )
        restricted = User(
            email="persona@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
        )
        db.session.add_all([admin, restricted])
        db.session.commit()
        cfg = SiteConfig.get()
        cfg._rolling_quote_sets = json.dumps(
            {
                "engineering": ["First, solve the problem. Then, write the code."],
                "productivity": ["Eat the frog first and the rest of the day is easy."],
                "laundry riddles": ["What gets wetter the more it dries? (A towel)"],
            }
        )
        cfg.active_quote_set = "laundry riddles"
        db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "quotes-admin@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.post(
        "/admin/site_config",
        data={
            "quote_permissions_dept": '{"A": ["engineering"]}',
            "quote_permissions_user": '{"persona@example.com": ["productivity"]}',
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200

    rv = client.get("/auth/settings")
    assert b"engineering" in rv.data
    assert b"productivity" in rv.data
    assert b"laundry riddles" in rv.data

    client.get("/auth/logout")
    rv = client.post(
        "/auth/login",
        data={"email": "persona@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/auth/settings")
    assert b"productivity" in rv.data
    assert b"engineering" not in rv.data
    assert b"laundry riddles" not in rv.data

    rv = client.get("/dashboard")
    assert rv.status_code == 200
    assert b"Eat the frog first" in rv.data
    assert b"What gets wetter the more it dries" not in rv.data


def test_site_config_fills_missing_or_empty_quote_sets(app):
    with app.app_context():
        cfg = SiteConfig.get()
        cfg._rolling_quote_sets = '{"default": [], "engineering": ["Ship it."], "motivational": []}'
        cfg.active_quote_set = "motivational"
        db.session.commit()

        refreshed = SiteConfig.get()
        quote_sets = refreshed.rolling_quote_sets

        assert set(SiteConfig.DEFAULT_QUOTE_SETS).issubset(set(quote_sets))
        for name, quotes in quote_sets.items():
            assert isinstance(quotes, list)
            assert quotes, f"{name} should always have at least one quote"

        assert quote_sets["default"] == SiteConfig.DEFAULT_QUOTE_SETS["default"]
        assert quote_sets["motivational"] == SiteConfig.DEFAULT_QUOTE_SETS["motivational"]
        # engineering was explicitly provided but should have been padded to 30
        eng = quote_sets["engineering"]
        assert eng[0] == "Ship it."
        assert len(eng) == 30
        assert refreshed.rolling_quotes == SiteConfig.DEFAULT_QUOTE_SETS["motivational"]


def test_admin_default_quote_and_user_override(app, client):
    # ensure admin default propagates and that user override persists
    with app.app_context():
        # admin user
        admin = User(
            email="admin2@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        # normal user
        u = User(
            email="user2@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
        )
        db.session.add(u)
        db.session.commit()
        # ensure site config exists with defaults
        cfg = SiteConfig.get()
        db.session.commit()

    # login as admin and change default
    rv = client.post(
        "/auth/login",
        data={"email": "admin2@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    # set default to "engineering"
    rv = client.post(
        "/admin/site_config",
        data={"active_quote_set": "engineering"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Site configuration saved" in rv.data

    # admin creates a user with quotes disabled
    rv = client.post(
        "/admin/users/new",
        data={
            "email": "preset@example.com",
            "password": "secret",
            "department": "A",
            "is_active": "y",
            "quotes_enabled": "",
            "quote_set": "engineering",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Created user preset@example.com" in rv.data

    # login as that new user, verify they cannot see quotes
    client.get("/auth/logout")
    rv = client.post(
        "/auth/login",
        data={"email": "preset@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/dashboard")
    assert b"rolling-quotes-data" not in rv.data
    # log out
    client.get("/auth/logout")

    # login as the normal user and check dashboard quote is from engineering
    rv = client.post(
        "/auth/login",
        data={"email": "user2@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/dashboard")
    assert rv.status_code == 200
    assert b"First, solve the problem." in rv.data

    # user selects own override
    rv = client.post(
        "/auth/settings",
        data={"quote_set": "coffee-humour"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/dashboard")
    assert b"Code runs faster after coffee." in rv.data

    # admin changes default again to productivity
    client.get("/auth/logout")
    client.post(
        "/auth/login",
        data={"email": "admin2@example.com", "password": "secret"},
        follow_redirects=True,
    )
    rv = client.post(
        "/admin/site_config",
        data={"active_quote_set": "productivity"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    client.get("/auth/logout")

    # login as user, override should still apply
    rv = client.post(
        "/auth/login",
        data={"email": "user2@example.com", "password": "secret"},
        follow_redirects=True,
    )
    rv = client.get("/dashboard")
    assert b"Code runs faster after coffee." in rv.data

    # new user without override should see productivity quote
    client.get("/auth/logout")
    with app.app_context():
        v = User(
            email="new@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
        )
        db.session.add(v)
        db.session.commit()
    rv = client.post(
        "/auth/login",
        data={"email": "new@example.com", "password": "secret"},
        follow_redirects=True,
    )
    rv = client.get("/dashboard")
    assert b"Eat the frog first" in rv.data


def test_admin_user_form_lists_custom_quote_sets(app, client):
    with app.app_context():
        admin = User(
            email="custom-admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        cfg = SiteConfig.get()
        cfg._rolling_quote_sets = json.dumps(
            {
                **SiteConfig.DEFAULT_QUOTE_SETS,
                "factory": [
                    "Tight tolerances start with steady process control.",
                ],
            }
        )
        db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "custom-admin@example.com", "password": "secret"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    rv = client.get("/admin/users/new")
    assert rv.status_code == 200
    assert b"(use site default)" in rv.data
    assert b"factory" in rv.data


def test_site_config_handles_db_errors_gracefully(app, client, monkeypatch):
    """If the database query for SiteConfig throws (e.g. missing columns),
    the admin page should still render and show a helpful flash message
    instead of raising a 500.
    """
    with app.app_context():
        # create superuser for login
        u = User(
            email="error-admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(u)
        db.session.commit()

    rv = login_admin(client, email="error-admin@example.com")
    assert rv.status_code == 200

    # monkeypatch SiteConfig.get to raise an exception simulating a broken schema
    monkeypatch.setattr(SiteConfig, "get", lambda: (_ for _ in ()).throw(Exception("boom")))

    rv = client.get("/admin/site_config", follow_redirects=True)
    assert rv.status_code == 200
    assert b"unable to load site configuration" in rv.data.lower()


def test_site_config_missing_table(app, client):
    """Dropping the site_config table should not cause a 500, route must flash
    an error and render a blank form."""
    from sqlalchemy import text

    with app.app_context():
        # ensure table exists then drop it manually
        db.session.execute(text("DROP TABLE IF EXISTS site_config"))
        db.session.commit()

        # create an admin user
        u = User(
            email="missing-table@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(u)
        db.session.commit()

    rv = login_admin(client, email="missing-table@example.com")
    assert rv.status_code == 200

    rv = client.get("/admin/site_config", follow_redirects=True)
    assert rv.status_code == 200
    data = rv.data.lower()
    # flash should warn about unable to load persisted config or schema issue
    assert b"unable to load site configuration" in data or b"schema" in data
    # form fields should still be present so admin could create a new table
    assert b"brand name" in data


def test_site_config_missing_columns(app, client):
    """If individual columns are missing from `site_config`, the page should
    warn about schema being out of date and not crash.  This simulates an
    upgraded codebase running against an older DB.
    """
    from sqlalchemy import text

    with app.app_context():
        # ensure table exists and has at least one row
        cfg = SiteConfig.get()
        db.session.commit()
        # drop each newer column one at a time and check behavior
        cols_to_drop = [
            'navbar_banner',
            'show_banner',
            'rolling_quotes',
            'rolling_quote_sets',
            'active_quote_set',
            'updated_at',
        ]
        for col in cols_to_drop:
            try:
                # SQLite doesn’t support DROP COLUMN; this will raise an OperationalError
                # so we catch and ignore it.  The goal is only to simulate a missing
                # column, not to suffer a hard crash during testing on sqlite.
                db.session.execute(text(f"ALTER TABLE site_config DROP COLUMN {col}"))
            except Exception:
                pass
        db.session.commit()

        u = User(
            email="missing-col@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(u)
        db.session.commit()

    rv = login_admin(client, email="missing-col@example.com")
    assert rv.status_code == 200

    rv = client.get("/admin/site_config", follow_redirects=True)
    assert rv.status_code == 200
    data = rv.data.lower()
    assert b"site configuration cannot be loaded" in data or b"schema" in data
    assert b"brand name" in data


def test_site_config_post_handles_commit_exception(app, client, monkeypatch):
    """If the database commit fails during a save, we flash an error but don't 500."""
    with app.app_context():
        u = User(
            email="save-error@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(u)
        db.session.commit()

    rv = login_admin(client, email="save-error@example.com")
    assert rv.status_code == 200

    # Cause commit to raise
    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(Exception("boom")))

    post_data = {"brand_name": "whatever"}
    rv = client.post("/admin/site_config", data=post_data, follow_redirects=True)
    assert rv.status_code == 200
    assert b"failed to save site configuration" in rv.data.lower()


def test_admin_dashboard_cards_navigate(app, client):
    with app.app_context():
        admin = User(
            email="admin-nav@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

    rv = login_admin(client, email="admin-nav@example.com")
    assert rv.status_code == 200

    rv = client.get("/admin/")
    assert rv.status_code == 200
    # ensure all cards are rendered as buttons with data-nav-url
    assert b"type=\"button\"" in rv.data
    if b"data-nav-url=\"/admin/list_users\"" not in rv.data:
        # dump html for debugging
        print("--- ADMIN INDEX HTML START ---")
        print(rv.data.decode(errors='replace'))
        print("--- ADMIN INDEX HTML END ---")
    assert b"data-nav-url=\"/admin/users\"" in rv.data
    assert b"data-nav-url=\"/admin/departments\"" in rv.data
    assert b"data-nav-url=\"/admin/site_config\"" in rv.data
    assert b"data-nav-url=\"/admin/site_config#quotes-settings\"" in rv.data
    assert b"data-nav-url=\"/admin/special_email\"" in rv.data
    assert b"data-nav-url=\"/admin/monitor\"" in rv.data
    assert b"data-nav-url=\"/admin/status_options\"" in rv.data
    assert b"data-nav-url=\"/admin/workflows\"" in rv.data
    assert b"data-nav-url=\"/admin/buckets\"" in rv.data
    assert b"data-nav-url=\"/admin/tenants\"" in rv.data
    assert b"onclick=\"window.location.assign('/admin/site_config'); return false;\"" in rv.data
    assert b"onclick=\"window.location.assign('/admin/site_config#quotes-settings'); return false;\"" in rv.data
    assert b"#quotes-settings" in rv.data
    assert b"/admin/special_email" in rv.data
    assert b"/admin/monitor" in rv.data
    assert b'data-nav-url="/admin/site_config"' in rv.data
    assert b'data-nav-url="/admin/site_config#quotes-settings"' in rv.data
    # some utility cards (switch-dept, notifications, etc.) are still
    # rendered as anchors; that's acceptable.  We already verify their
    # urls above.
    # (The previous regression test used to forbid any anchors, but the
    # dashboard layout intentionally uses a mix of <button> and <a> now.)
    # ensure no href with javascript scheme anywhere
    assert b"href=\"javascript:" not in rv.data

    # Smoke-test every rendered admin dashboard card so the test stays in sync
    # with the actual dashboard markup.
    html = rv.get_data(as_text=True)
    urls = re.findall(r'data-nav-url="([^"]+)"', html)
    assert urls, "Expected admin dashboard cards with data-nav-url"
    # our new switch-department card should be present
    assert "/auth/choose_dept" in urls
    # notifications card should also always exist
    assert "/admin/notifications_retention" in urls
    # href attributes should match data-nav-url and begin with '/'
    hrefs = re.findall(r'href="([^"]+)"', html)
    for u in urls:
        assert u.startswith('/'), f"unexpected url {u}"
        if u not in {"/admin/site_config", "/admin/site_config#quotes-settings"}:
            assert u in hrefs, f"href for {u} missing"

    for url in urls:
        # Browser fragments are client-side only; request the route itself.
        route = url.split("#", 1)[0]
        resp = client.get(route, follow_redirects=False)
        assert resp.status_code in (200, 302), route

    # Also check department-specific monitor variants that are not separate
    # cards but are important admin navigation targets.
    for route in ("/admin/monitor?dept=B", "/admin/monitor?dept=C"):
        resp = client.get(route, follow_redirects=False)
        assert resp.status_code in (200, 302), route


def test_base_template_bumps_static_asset_version(client):
    rv = client.get("/auth/login")
    assert rv.status_code == 200
    # versions bump whenever CSS/JS changes so browsers refetch
    assert b"/static/styles.css?v=20260309d" in rv.data
    # main script may either be the legacy path or the built bundle in `dist`
    assert b"/static/app.js?v=20260309d" in rv.data or b"/static/dist/app.js?v=" in rv.data


def test_login_next_redirection(client, app):
    """If an unauthenticated user hits a protected page, the login form
    should accept a *next* value and redirect back after successful auth.
    """
    with app.app_context():
        u = User(
            email="admin-next@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(u)
        db.session.commit()

    # attempt to reach a protected admin route
    rv = client.get("/admin/site_config", follow_redirects=False)
    assert rv.status_code == 302
    login_loc = rv.headers.get("Location")
    assert login_loc and login_loc.startswith("/auth/login")
    # ensure next parameter is included and points at the original path
    assert "next=%2Fadmin%2Fsite_config" in login_loc

    # fetch login page to ensure hidden field is rendered
    rv2 = client.get(login_loc)
    assert rv2.status_code == 200
    html = rv2.get_data(as_text=True)
    assert 'name="next"' in html
    assert '/admin/site_config' in html

    # perform login using the same URL; admins now honour the `next`
    # value directly and skip the department picker entirely.
    rv3 = client.post(login_loc, data={"email": "admin-next@example.com", "password": "secret"}, follow_redirects=True)
    assert rv3.status_code == 200
    # we should land on the site config page itself rather than seeing the
    # department chooser; confirm by path and header text
    assert rv3.request.path == "/admin/site_config"
    assert b"Site Configuration" in rv3.data
    assert b"Select Department" not in rv3.data

    # there is no need to simulate a switch_dept call; the next parameter was
    # handled during login


def test_banner_html_is_sanitized_and_does_not_break_navigation(app, client):
    with app.app_context():
        admin = User(
            email="admin-banner@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

    rv = login_admin(client, email="admin-banner@example.com")
    assert rv.status_code == 200

    malicious_banner = '<a href="/static/app.js?v=20260308b">bad</a><form action="/static/styles.css?v=20260308b"><button>go</button></form><script>alert(1)</script><div>Safe text</div>'
    rv = client.post(
        "/admin/site_config",
        data={
            "brand_name": "Safe Banner",
            "theme_preset": "default",
            "banner_html": malicious_banner,
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200

    with app.app_context():
        cfg = SiteConfig.get()
        assert cfg.banner_html is not None
        assert "<script" not in cfg.banner_html
        assert "/static/app.js" not in cfg.banner_html
        assert "/static/styles.css" not in cfg.banner_html

    nav_attr_re = re.compile(r'<(?:a|form|button)\b[^>]*(?:href|action|formaction)="([^"]+)"')
    for route in ("/admin/", "/admin/site_config", "/admin/metrics_config", "/dashboard"):
        page = client.get(route)
        assert page.status_code == 200, route
        html = page.get_data(as_text=True)
        nav_targets = nav_attr_re.findall(html)
        assert not any(target.startswith('/static/') for target in nav_targets), route

    # existing unsafe banner content should also be sanitized at render time
    with app.app_context():
        cfg = SiteConfig.get()
        cfg.banner_html = '<a href="/static/app.js?v=20260307d">bad</a><div>still safe</div>'
        db.session.add(cfg)
        db.session.commit()

    page = client.get("/admin/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    nav_targets = nav_attr_re.findall(html)
    assert not any(target.startswith('/static/') for target in nav_targets)


def test_migration_status_warning_uses_specific_class(app, client):
    with app.app_context():
        admin = User(
            email="admin-migration@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

    rv = login_admin(client, email="admin-migration@example.com")
    assert rv.status_code == 200

    rv = client.get("/admin/migrations/status")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert "migration-status-warning" in html or "No unapplied migrations detected." in html
