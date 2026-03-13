"""Application factory and CLI helpers.

create_app() constructs the Flask application, initializes extensions
(database, login manager, optional Flask-Migrate), registers blueprints,
and sets up development CLI helpers used by maintainers.

This module intentionally keeps initialization deterministic so tests
and local scripts can create the app with `create_app()`.
"""

import os

import click
from dotenv import load_dotenv
from flask import Flask, current_app
from flask_login import current_user
from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash
from werkzeug.exceptions import HTTPException

from config import Config

from .extensions import db, login_manager, migrate
from .models import User
from .utils.user_context import (
    avatar_url_for,
    can_view_metrics_for_user,
    get_user_departments,
    gravatar_url,
    is_external_theme_active,
    user_has_multiple_departments,
)

# Module-level CSRFProtect instance so other modules can use `from app import csrf`
csrf = CSRFProtect()

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    # Allow runtime override of DB URL so tests can monkeypatch env before calling create_app()
    db_url = os.getenv("DATABASE_URL", app.config.get("SQLALCHEMY_DATABASE_URI"))
    # Normalize legacy `postgres://` scheme to SQLAlchemy-compatible `postgresql://`
    if isinstance(db_url, str) and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    # Improved error logging: log exceptions to stdout
    import logging
    import sys
    import traceback
    from flask import got_request_exception, jsonify
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.ERROR)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.ERROR)
    def log_exception(sender, exception, **extra):
        sender.logger.error("Exception occurred", exc_info=exception)
    got_request_exception.connect(log_exception, app)

    @app.errorhandler(500)
    def internal_error(error):
        logging.error("Internal Server Error: %s", error)
        logging.error(traceback.format_exc())
        return jsonify({"error": "Internal Server Error", "details": str(error)}), 500

    # Optionally, log all exceptions
    @app.errorhandler(Exception)
    def handle_exception(e):
        import logging, traceback
        # If it's an HTTPException (like 403), return its default handler
        if isinstance(e, HTTPException):
            return e
        logging.error("Unhandled Exception: %s", e)
        logging.error(traceback.format_exc())
        from flask import jsonify
        return jsonify({"error": "Unhandled Exception", "details": str(e)}), 500

    # We will perform a one-time schema check (original_sender column) after
    # the database extension is initialized later in this function.  Doing it
    # upfront would require calling `db.init_app` twice, which breaks the
    # tests.
    #
    # The check is implemented further down (after the main init section).
    pass

    @app.cli.command("notify-due")
    def notify_due():
        from .notifications.due import send_due_soon_notifications
        from .services.job_dispatcher import run_job

        # Persist notifications when run as a CLI command during deploy
        run_job(
            "notify_due",
            send_due_soon_notifications,
            current_app,
            hours=24,
            commit=True,
            queue_name="maintenance",
            payload={"hours": 24},
        )

    def _run_notify_reminders():
        from .notifications.due import send_high_priority_nudges
        from .services.job_dispatcher import run_job

        # Persist notifications when run as a CLI command during deploy
        run_job(
            "notify_nudges",
            send_high_priority_nudges,
            current_app,
            commit=True,
            queue_name="maintenance",
            payload={"kind": "high_priority_nudges"},
        )

    @app.cli.command("notify-nudges")
    def notify_nudges():
        _run_notify_reminders()

    @app.cli.command("notify-reminders")
    def notify_reminders():
        _run_notify_reminders()

    @app.cli.command("check-config")
    def check_config():
        """Validate environment-derived configuration values.

        Returns an error code if any checks fail so deploy scripts can halt early.
        """
        errors = Config.validate(app)
        if errors:
            for e in errors:
                click.echo(f"ERROR: {e}")
            # indicate failure -- `flask` will exit nonzero
            raise click.Abort()
        click.echo("Configuration OK")

    @app.cli.command("clear-open-requests")
    @click.confirmation_option(
        prompt="Are you sure you want to close all open requests?"
    )
    def clear_open_requests():
        """Close all non-closed requests by setting their status to CLOSED and clearing assignment."""
        from .models import Request

        with app.app_context():
            try:
                q = Request.query.filter(Request.status != "CLOSED")
                count = q.count()
                if count == 0:
                    click.echo("No open requests found.")
                    return
                q.update(
                    {"status": "CLOSED", "assigned_to_user_id": None},
                    synchronize_session=False,
                )
                db.session.commit()
                click.echo(f"Closed {count} open requests.")
            except Exception as e:
                db.session.rollback()
                click.echo(f"Failed to clear open requests: {e}")

    @app.cli.command("create-user")
    @click.option("--email", required=True, help="User email")
    @click.option("--name", default=None, help="Display name")
    @click.option(
        "--department",
        default="A",
        type=click.Choice(["A", "B", "C"], case_sensitive=False),
    )
    @click.option("--password", default="password123", help="Password for local login")
    def create_user_cli(email, name, department, password):
        """Create a local user (dev/test)."""
        email_n = email.strip().lower()
        with app.app_context():
            existing = User.query.filter_by(email=email_n).first()
            if existing:
                click.echo(
                    f"User {email_n} already exists; updating department/name/password"
                )
                existing.department = department.upper()
                existing.name = name or existing.name
                # Avoid relying on environment-specific default hash methods (e.g. scrypt)
                existing.password_hash = generate_password_hash(
                    password, method="pbkdf2:sha256"
                )
                existing.is_active = True
                db.session.commit()
                return
            u = User(
                email=email_n,
                name=name,
                department=department.upper(),
                # Use a compatible hashing method across runtimes
                password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
                is_active=True,
            )
            db.session.add(u)
            db.session.commit()
            click.echo(f"Created {email_n} in Dept {department.upper()}")

    @app.cli.command("onboard-tenant")
    @click.option("--slug", required=True, help="Tenant slug (unique identifier)")
    @click.option("--name", required=True, help="Human-readable tenant name")
    @click.option(
        "--admin-email", required=True, help="Email address for initial admin user"
    )
    @click.option(
        "--admin-password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Password for the new admin account",
    )
    def onboard_tenant(slug, name, admin_email, admin_password):
        """Create a tenant with defaults and an initial admin user."""
        from .extensions import db
        from .models import Department, FeatureFlags, Tenant, TenantMembership, User

        slug = slug.strip().lower()
        name = name.strip()
        tenant = Tenant.query.filter_by(slug=slug).first()
        if not tenant:
            tenant = Tenant(slug=slug, name=name, is_active=True)
            db.session.add(tenant)
            db.session.commit()
            click.echo(f"Created tenant '{slug}'")
        else:
            click.echo(f"Tenant '{slug}' already exists, updating name")
            tenant.name = name
            tenant.is_active = True
            db.session.commit()

        # create default departments if missing
        for code in ["A", "B", "C"]:
            if not Department.query.filter_by(code=code).first():
                db.session.add(
                    Department(code=code, name=f"Dept {code}", order=0, is_active=True)
                )
        db.session.commit()

        # attach default feature flags
        ff = FeatureFlags.get()
        ff.enable_notifications = True
        db.session.add(ff)
        db.session.commit()

        # create or update admin user
        user = User.query.filter_by(email=admin_email).first()
        if not user:
            user = User(
                email=admin_email,
                department="A",
                password_hash=generate_password_hash(
                    admin_password, method="pbkdf2:sha256"
                ),
                is_active=True,
                is_admin=True,
            )
            db.session.add(user)
            db.session.commit()
            click.echo(f"Created admin user {admin_email}")
        else:
            user.password_hash = generate_password_hash(
                admin_password, method="pbkdf2:sha256"
            )
            user.is_active = True
            user.is_admin = True
            user.department = "A"
            db.session.commit()
            click.echo(f"Updated admin user {admin_email}")

        # make membership record for tenant
        if not TenantMembership.query.filter_by(
            tenant_id=tenant.id, user_id=user.id
        ).first():
            tm = TenantMembership(
                tenant_id=tenant.id,
                user_id=user.id,
                role="admin",
                is_active=True,
                is_default=True,
            )
            db.session.add(tm)
            db.session.commit()
            click.echo(f"Added {admin_email} as tenant admin")
        else:
            click.echo(f"Admin membership for {admin_email} already exists")

    # Init OAuth (SSO)
    from .auth.sso import init_oauth

    init_oauth(app)

    # Optional Sentry initialization (guarded by SENTRY_DSN)
    try:
        from .extensions import init_sentry

        init_sentry(app)
    except Exception:
        pass

    # Optional security/runtime middleware
    try:
        from .middleware import init_runtime_middleware, init_security

        init_runtime_middleware(app)
        init_security(app)
    except Exception:
        pass

    # Upload folder (best-effort; serverless may not allow writes)
    upload_folder = app.config.get("UPLOAD_FOLDER")
    if upload_folder:
        try:
            os.makedirs(upload_folder, exist_ok=True)
        except OSError:
            pass

    db.init_app(app)

    # post-initialization schema guard for production; identical to the
    # migration fallback in scripts/release_tasks.py.
    try:
        from sqlalchemy import inspect, text
        insp = inspect(db.engine)
        if "request" in insp.get_table_names():
            cols = [c["name"] for c in insp.get_columns("request")]
            if "original_sender" not in cols:
                app.logger.warning("adding missing column original_sender on request")
                db.engine.execute(
                    text("ALTER TABLE request ADD COLUMN IF NOT EXISTS original_sender VARCHAR(255)")
                )
    except Exception:
        pass

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    # Initialize request lifecycle hooks (register listeners for Request create/update)
    try:
        from .services.request_hooks import init_request_hooks

        init_request_hooks(app)
    except Exception:
        # If hooks can't be registered (e.g., during migrations), continue silently
        pass

    try:
        from .services.tenant_context import init_tenant_context

        init_tenant_context(app)
    except Exception:
        pass
    # Enable CSRF protection for all forms (create module-level instance so
    # individual routes can be exempted when necessary)
    from . import csrf as _csrf  # local import to ensure module-level var exists

    _csrf.init_app(app)

    # Initialize optional caching and Redis client if available.
    try:
        from .extensions import cache, init_redis_client

        try:
            cache.init_app(
                app,
                config={
                    "CACHE_TYPE": "flask_caching.backends.rediscache.RedisCache",
                    "CACHE_REDIS_URL": app.config.get("REDIS_URL"),
                    "CACHE_DEFAULT_TIMEOUT": app.config.get(
                        "CACHE_DEFAULT_TIMEOUT", 300
                    ),
                },
            )
        except Exception:
            # If Flask-Caching isn't installed or config invalid, continue without cache.
            try:
                app.logger.info("Cache not initialized (missing package or config)")
            except Exception:
                pass
        try:
            init_redis_client(app)
        except Exception:
            pass
    except Exception:
        # Optional cache/redis not available; proceed.
        pass

    # Initialize Flask-Migrate (Alembic) for DB migrations if available
    try:
        if migrate is not None:
            migrate.init_app(app, db)
    except Exception:
        # If Flask-Migrate isn't installed in this environment, skip init
        pass

    @app.teardown_request
    def _teardown_request(exc):
        # Ensure any failed/aborted DB transaction is rolled back so a
        # subsequent request doesn't reuse a bad transaction state.
        if exc:
            try:
                db.session.rollback()
            except Exception:
                pass
        try:
            db.session.remove()
        except Exception:
            pass

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            # If the DB/tables aren't ready (e.g., fresh deploy with SQLite),
            # avoid raising an exception during request handling and treat
            # the visitor as anonymous so the app can return a login page
            # instead of a 500. Rollback the session to clear any aborted
            # transactions so subsequent requests do not reuse a bad
            # connection/transaction state.
            try:
                db.session.rollback()
            except Exception:
                pass
            return None

    # Apply impersonation override on each request: if an admin has started an
    # acting-as session, temporarily present them as a member of the target dept.
    @app.before_request
    def _apply_impersonation():
        from flask_login import current_user

        try:
            if not current_user or not getattr(current_user, "is_authenticated", False):
                return
        except Exception:
            return

        try:
            if not hasattr(current_user, "_stored_primary_department"):
                current_user._stored_primary_department = getattr(
                    current_user, "department", None
                )
        except Exception:
            pass

        imp_admin = None
        from flask import current_app as _current_app
        from flask import session as _session

        # only honor impersonation if the flag is enabled; otherwise the
        # session keys are ignored.
        if _current_app.config.get("ALLOW_IMPERSONATION"):
            imp_admin = _session.get("impersonate_admin_id")
            imp_dept = _session.get("impersonate_dept")
            if (
                imp_admin
                and imp_dept
                and int(imp_admin) == int(getattr(current_user, "id", -1))
            ):
                # Override department for permission checks and templates for duration of request.
                try:
                    current_user.department = imp_dept
                    current_user.is_acting_as = True
                    current_user.act_as_label = f"Acting as Dept {imp_dept}"
                except Exception:
                    pass
        # Honor a user-selected active department stored in session. This
        # allows users assigned to multiple departments to switch their
        # active context without changing their stored primary department.
        try:
            active_dept = _session.get("active_dept")
            if active_dept:
                # Validate that the current user is allowed to view as this dept
                try:
                    from .utils.user_context import user_can_access_department

                    allowed = False
                    # Always allow switching to primary department
                    if getattr(current_user, "department", None) == active_dept:
                        allowed = True
                    # Admins may switch freely
                    if getattr(current_user, "is_admin", False):
                        allowed = True
                    if not allowed:
                        allowed = user_can_access_department(current_user, active_dept)
                    if allowed:
                        try:
                            current_user.department = active_dept
                            current_user.is_switched_dept = True
                            current_user.act_as_label = f"Viewing as Dept {active_dept}"
                        except Exception:
                            pass
                except Exception:
                    # If any DB error occurs while validating, rollback the
                    # session to avoid leaving the connection in an aborted
                    # transaction state which would affect subsequent queries.
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    # fall back to no-op
                    pass
        except Exception:
            pass
        return

    from .admin.routes import admin_bp
    from .auth.routes import auth_bp
    from .external.routes import external_bp
    from .integrations.webhooks import integrations_bp
    from .notifications.routes import notifications_bp
    from .requests_bp import requests_bp
    from .verify import verify_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(external_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(integrations_bp)
    # versioned public API
    try:
        from .api.v1 import api_v1_bp

        app.register_blueprint(api_v1_bp)
    except ImportError:
        # during early bootstrap (tests, minimal env) the new api package
        # may not yet be available; ignore and continue
        pass
    # camera/ocr verification helper
    app.register_blueprint(verify_bp)

    # Provide active theme CSS and logo URL to templates
    @app.context_processor
    def _theme_context():
        try:
            from flask import url_for

            from .models import Department, FeatureFlags, SiteConfig

            css = ""
            logo = current_app.config.get("LOGO_URL")
            brand_name = "FreshProcess"
            site_theme_preset = "default"
            dept_labels = {"A": "Dept A", "B": "Dept B", "C": "Dept C"}
            external_theme_loaded = False
            cfg = None

            # Theme model is optional in some environments/tests.
            try:
                from .models import AppTheme

                t = AppTheme.query.filter_by(active=True).first()
                css = t.css if t and t.css else ""
                if t and t.logo_filename:
                    try:
                        if t.logo_filename.startswith("http"):
                            logo = t.logo_filename
                        else:
                            logo = url_for("static", filename=t.logo_filename)
                    except Exception:
                        pass
            except Exception:
                pass

            # site config (singleton)
            try:
                quote_user = None
                selected_quote_key = None
                try:
                    if current_user.is_authenticated:
                        try:
                            db.session.expire_all()
                        except Exception:
                            pass
                        quote_user = db.session.get(User, current_user.id)
                except Exception:
                    quote_user = None
                cfg = SiteConfig.get()
                external_theme_loaded = is_external_theme_active(cfg)
                banner_html = cfg.banner_html or ""
                try:
                    from .admin.routes import _sanitize_banner_html

                    banner_html = _sanitize_banner_html(banner_html)
                except Exception:
                    pass
                rolling_quotes_enabled = bool(cfg.rolling_quotes_enabled)
                rolling_quotes = cfg.rolling_quotes or []
                # allow user to disable quotes entirely
                if quote_user and getattr(quote_user, "quotes_enabled", True) is False:
                    rolling_quotes = []
                else:
                    try:
                        selected_quote_key = cfg.resolve_quote_set_name_for_user(
                            quote_user
                        )
                        if selected_quote_key:
                            # prefer configured sets if present, otherwise fall
                            # back to built-in defaults so personal overrides
                            # still work without any admin customization.
                            if cfg.rolling_quote_sets:
                                rolling_quotes = cfg.rolling_quote_sets.get(
                                    selected_quote_key, []
                                )
                            else:
                                rolling_quotes = SiteConfig.DEFAULT_QUOTE_SETS.get(
                                    selected_quote_key, []
                                )
                    except Exception:
                        pass
                if getattr(cfg, "logo_filename", None):
                    try:
                        logo = url_for("static", filename=cfg.logo_filename)
                    except Exception:
                        pass
                if getattr(cfg, "brand_name", None):
                    brand_name = cfg.brand_name
                if getattr(cfg, "theme_preset", None):
                    site_theme_preset = (cfg.theme_preset or "default").strip().lower()
                    if site_theme_preset not in (
                        "default",
                        "sky",
                        "moss",
                        "dawn",
                        "twilight",
                    ):
                        site_theme_preset = "default"
            except Exception:
                banner_html = ""
                rolling_quotes_enabled = False
                rolling_quotes = []
                selected_quote_key = None

            # If an external theme/logo is present we intentionally
            # suppress the rolling quotes UI to preserve imported branding.
            try:
                if external_theme_loaded:
                    rolling_quotes_enabled = False
            except Exception:
                pass

            # Authenticated users can still opt into personalized rotating
            # quotes on signed-in pages even when the public/login banner is
            # off, provided quotes are available for their selected/default set.
            try:
                if (
                    current_user.is_authenticated
                    and quote_user
                    and getattr(quote_user, "quotes_enabled", True)
                    and rolling_quotes
                ):
                    rolling_quotes_enabled = True
            except Exception:
                pass

            # Respect the global feature flag as well (admin toggle).
            allow_user_reminders_enabled = False
            guest_dashboard_enabled = True
            guest_submission_enabled = True
            try:
                ff = FeatureFlags.get()
                # Respect the admin rolling-quotes flag independently from
                # the global vibe button flag. Disabling the vibe control
                # should hide the button while still allowing quote-only
                # banner UI to remain visible when rolling quotes are enabled.
                if getattr(ff, "rolling_quotes_enabled", True) is False:
                    rolling_quotes_enabled = False
                allow_user_reminders_enabled = bool(
                    getattr(ff, "allow_user_nudges", False)
                )
                guest_dashboard_enabled = bool(
                    getattr(ff, "guest_dashboard_enabled", True)
                )
                guest_submission_enabled = bool(
                    getattr(ff, "guest_submission_enabled", True)
                )
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass

            try:
                if (
                    not current_user.is_authenticated
                    and request.endpoint == "auth.login"
                    and rolling_quotes_enabled
                ):
                    rolling_quotes = SiteConfig.DEFAULT_QUOTE_SETS.get(
                        "default",
                        [],
                    )
            except Exception:
                pass

            try:
                rows = (
                    Department.query.filter_by(is_active=True)
                    .order_by(Department.order.asc(), Department.code.asc())
                    .all()
                )
                for d in rows:
                    code = (d.code or "").upper().strip()
                    label = (d.label or "").strip()
                    if code and label:
                        dept_labels[code] = label
            except Exception:
                pass

            return dict(
                active_theme_css=css,
                theme_logo_url=logo,
                site_brand_name=brand_name,
                site_theme_preset=site_theme_preset,
                department_labels=dept_labels,
                site_banner_html=banner_html,
                company_url=getattr(cfg, "company_url", None),
                rolling_quotes_enabled=rolling_quotes_enabled,
                rolling_quotes=rolling_quotes,
                # choose an initial quote to render server-side; fallback to the
                # first entry of the active list or the default set.  this
                # ensures that when JS fails or loads slowly the placeholder is
                # replaced with something meaningful.
                initial_quote=(
                    # select a fresh random entry each time instead of using a
                    # day‑based deterministic shuffle; this keeps the sequence
                    # unpredictable even within the same day.
                    (
                        lambda quotes, enabled: (
                            __import__("random").choice(quotes)
                            if quotes and enabled
                            else None
                        )
                    )(
                        rolling_quotes[:] if rolling_quotes else [],
                        rolling_quotes_enabled,
                    )
                    if rolling_quotes and rolling_quotes_enabled
                    else (SiteConfig.DEFAULT_QUOTE_SETS.get("motivational", [None])[0])
                ),
                allow_user_reminders_enabled=allow_user_reminders_enabled,
                guest_dashboard_enabled=guest_dashboard_enabled,
                guest_submission_enabled=guest_submission_enabled,
                external_theme_loaded=external_theme_loaded,
                FeatureFlags=FeatureFlags,
            )
        except Exception:
            # if any part of the helper blows up (e.g. missing schema), still
            # return a minimal set of values that won't break templates.  we
            # try to provide a basic FeatureFlags object because the navbar
            # code accesses `FeatureFlags.get().vibe_enabled`.
            ff = None
            try:
                ff = FeatureFlags.get()
            except Exception:

                class _Dummy:
                    vibe_enabled = False

                ff = _Dummy()
            return dict(
                active_theme_css="",
                theme_logo_url=current_app.config.get("LOGO_URL"),
                site_brand_name="FreshProcess",
                site_theme_preset="default",
                department_labels={"A": "Dept A", "B": "Dept B", "C": "Dept C"},
                site_banner_html="",
                rolling_quotes_enabled=False,
                rolling_quotes=[],
                company_url=None,
                initial_quote=None,
                allow_user_reminders_enabled=False,
                guest_dashboard_enabled=True,
                guest_submission_enabled=True,
                external_theme_loaded=False,
                FeatureFlags=ff,
            )

    # Track the last successfully rendered GET URL in the session so that
    # when the DB is temporarily unavailable we can redirect users back to
    # the last working page instead of showing a persistent 503 on refresh.
    from flask import request as _request
    from flask import session as _session

    @app.after_request
    def _store_last_good(response):
        try:
            # Only store successful GET responses (status < 400).
            if _request.method == "GET" and response.status_code < 400:
                try:
                    _session["last_good_url"] = _request.url
                except Exception:
                    # Session may be unavailable in some contexts; ignore.
                    pass
        except Exception:
            pass
        return response

    # DEV ONLY: auto-create tables
    # NOTE: For production we prefer running Alembic migrations during the
    # release step. Default AUTO_CREATE_DB is now False to avoid implicit
    # create_all() in deployed instances. Set `AUTO_CREATE_DB=true` locally
    # if you want the convenience behavior during development.
    if os.getenv("AUTO_CREATE_DB", "False") == "True":
        with app.app_context():
            db.create_all()

    # Lightweight request-time DB readiness check so navigation to admin and
    # other app pages fails gracefully while the database is still starting.
    try:
        from flask import request as _request
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError

        @app.before_request
        def _ensure_database_ready_before_request():
            endpoint = (_request.endpoint or "").strip()
            path = (_request.path or "").strip()

            # Skip static assets, health probes, and common auth endpoints.
            if endpoint == "static" or path == "/health":
                return None
            if endpoint.startswith("auth."):
                return None
            if path.startswith("/static/"):
                return None

            try:
                db.session.execute(text("SELECT 1"))
            except OperationalError as err:
                app.logger.warning(
                    "Database readiness check failed for %s: %s", path, err
                )
                return (
                    "Service temporarily unavailable — database initializing. Please try again shortly.",
                    503,
                )
            except Exception:
                # Defer non-operational errors to the normal request flow.
                return None

    except Exception:
        pass

    # Return a friendly 503 when the database isn't ready instead of a 500.
    # This avoids exposing a stacktrace to end users during rolling deploys
    # when a machine may briefly not have the DB/tables available.
    try:
        from sqlalchemy.exc import OperationalError

        @app.errorhandler(OperationalError)
        def _handle_db_op_error(err):
            app.logger.exception("Database operational error handled: %s", err)
            # If we have a recorded last-good URL in the user's session, try
            # redirecting them there so a browser refresh will return them to
            # a previously loaded page instead of repeatedly showing the 503.
            try:
                from flask import redirect
                from flask import request as _request
                from flask import session as _session

                last = _session.get("last_good_url")
                # Avoid redirect loops: don't redirect back to the same failing URL
                if last and last != _request.url:
                    app.logger.info(
                        "Redirecting to last good URL after DB error: %s", last
                    )
                    return redirect(last)
            except Exception:
                pass

            return (
                "Service temporarily unavailable — database initializing. Please try again shortly.",
                503,
            )

    except Exception:
        # If SQLAlchemy isn't available for some reason, skip installing the handler.
        pass

    try:
        from flask import jsonify, render_template, request

        @app.errorhandler(429)
        def _handle_rate_limit(_err):
            wants_json = request.path.startswith("/integrations/") or (
                request.accept_mimetypes.best == "application/json"
            )
            if wants_json:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "rate_limited",
                            "message": "Too many requests. Please try again later.",
                        }
                    ),
                    429,
                )
            return (render_template("429.html"), 429)

    except Exception:
        pass

    # Friendly handling for expired/invalid CSRF tokens (common during prototyping).
    try:
        from flask import flash, redirect, url_for
        from flask_wtf.csrf import CSRFError

        @app.errorhandler(CSRFError)
        def _handle_csrf_error(err):
            app.logger.warning("CSRF error handled: %s", err)
            # Inform the user and redirect to login where a fresh token will be issued
            flash(
                "Session expired or invalid form submission — please try again.",
                "warning",
            )
            return redirect(url_for("auth.login"))

    except Exception:
        pass
    except Exception:
        # If SQLAlchemy isn't available for some reason, skip installing the handler.
        pass

    # Runtime health endpoints for liveness/readiness probes.
    from flask import g, jsonify

    def _build_health_payload(*, check_dependencies: bool):
        payload = {
            "request_id": getattr(g, "request_id", None),
            "status": "ok",
        }
        include_details = app.config.get("HEALTHCHECK_INCLUDE_DETAILS", True)
        components = {}
        failures = []

        if check_dependencies:
            try:
                from sqlalchemy import text

                db.session.execute(text("SELECT 1"))
                components["database"] = {"status": "ok"}
            except Exception as e:
                components["database"] = {
                    "status": "unhealthy",
                    "error": str(e),
                }
                failures.append("database")

            redis_required = bool(app.config.get("HEALTHCHECK_REDIS_REQUIRED"))
            redis_url = app.config.get("REDIS_URL")
            try:
                from .extensions import init_redis_client
                from .extensions import redis_client as _redis_client
            except Exception:
                _redis_client = None
                init_redis_client = None

            if redis_required or redis_url:
                try:
                    if _redis_client is None and init_redis_client is not None:
                        _redis_client = init_redis_client(app)
                    if _redis_client is None:
                        raise RuntimeError("redis client not initialized")
                    _redis_client.ping()
                    components["redis"] = {"status": "ok"}
                except Exception as e:
                    components["redis"] = {
                        "status": "unhealthy" if redis_required else "skipped",
                        "error": str(e),
                        "required": redis_required,
                    }
                    if redis_required:
                        failures.append("redis")

        if failures:
            payload["status"] = "unhealthy"
            payload["failed_checks"] = failures

        if include_details:
            payload["components"] = components

        return payload, 503 if failures else 200

    @app.route("/health")
    def _health():
        payload, status_code = _build_health_payload(check_dependencies=False)
        return jsonify(payload), 200 if status_code < 500 else status_code

    @app.route("/ready")
    def _ready():
        try:
            payload, status_code = _build_health_payload(check_dependencies=True)
            return jsonify(payload), status_code
        except Exception as e:
            app.logger.warning("Readiness check failed: %s", e)
            return (
                jsonify(
                    {
                        "status": "unhealthy",
                        "request_id": getattr(g, "request_id", None),
                    }
                ),
                503,
            )

    # Optionally wait for DB readiness during app startup. When the
    # `WAIT_FOR_DB` env var is set to a truthy value, the application will
    # attempt a simple `SELECT 1` repeatedly before returning the app
    # instance. This is helpful for deployments where the DB may not be
    # immediately reachable at process start (e.g. cloud services).
    if os.getenv("WAIT_FOR_DB", "False") == "True":
        import time

        from sqlalchemy import text

        with app.app_context():
            for _ in range(30):
                try:
                    db.session.execute(text("SELECT 1"))
                    app.logger.info("Database reachable, continuing startup")
                    break
                except Exception:
                    app.logger.info("Waiting for database to become available...")
                    time.sleep(2)
            else:
                app.logger.warning("Timed out waiting for database (proceeding anyway)")

    # Ensure recommended default buckets exist for Dept B unless explicitly disabled.
    # This provides sensible defaults for the Dept B dashboard when a fresh DB
    # is created or when a deploy doesn't include seeded data. Admins can still
    # edit or replace buckets via the admin UI.
    try:
        if os.getenv("SEED_DEFAULT_BUCKETS", "True").lower() != "false":
            from .models import BucketStatus, Department, StatusBucket

            try:
                with app.app_context():
                    # Ensure default Department rows exist (A/B/C) so code treating
                    # them as persisted departments behaves consistently.
                    for code, label, order in (
                        ("A", "Dept A", 0),
                        ("B", "Dept B", 1),
                        ("C", "Dept C", 2),
                    ):
                        existing = Department.query.filter_by(code=code).first()
                        if not existing:
                            d = Department(
                                code=code, label=label, is_active=True, order=order
                            )
                            db.session.add(d)
                    db.session.flush()

                    # Only seed buckets if Dept B has no buckets configured.
                    if StatusBucket.query.filter_by(department_name="B").count() == 0:
                        # New
                        nb = StatusBucket(
                            name="New", department_name="B", order=0, active=True
                        )
                        db.session.add(nb)
                        db.session.flush()
                        db.session.add(
                            BucketStatus(
                                bucket_id=nb.id, status_code="NEW_FROM_A", order=0
                            )
                        )

                        # In Progress
                        ip = StatusBucket(
                            name="In Progress",
                            department_name="B",
                            order=1,
                            active=True,
                        )
                        db.session.add(ip)
                        db.session.flush()
                        db.session.add(
                            BucketStatus(
                                bucket_id=ip.id, status_code="B_IN_PROGRESS", order=0
                            )
                        )
                        db.session.add(
                            BucketStatus(
                                bucket_id=ip.id, status_code="PENDING_C_REVIEW", order=1
                            )
                        )
                        db.session.add(
                            BucketStatus(
                                bucket_id=ip.id, status_code="B_FINAL_REVIEW", order=2
                            )
                        )

                        # Needs Input / Waiting
                        ni = StatusBucket(
                            name="Needs Input",
                            department_name="B",
                            order=2,
                            active=True,
                        )
                        db.session.add(ni)
                        db.session.flush()
                        db.session.add(
                            BucketStatus(
                                bucket_id=ni.id,
                                status_code="WAITING_ON_A_RESPONSE",
                                order=0,
                            )
                        )
                        db.session.add(
                            BucketStatus(
                                bucket_id=ni.id, status_code="C_NEEDS_CHANGES", order=1
                            )
                        )

                        # Pending Approval
                        pa = StatusBucket(
                            name="Pending Approval",
                            department_name="B",
                            order=3,
                            active=True,
                        )
                        db.session.add(pa)
                        db.session.flush()
                        db.session.add(
                            BucketStatus(
                                bucket_id=pa.id, status_code="EXEC_APPROVAL", order=0
                            )
                        )
                        db.session.add(
                            BucketStatus(
                                bucket_id=pa.id, status_code="C_APPROVED", order=1
                            )
                        )
                        db.session.add(
                            BucketStatus(
                                bucket_id=pa.id, status_code="SENT_TO_A", order=2
                            )
                        )

                        # Completed
                        comp = StatusBucket(
                            name="Completed", department_name="B", order=4, active=True
                        )
                        db.session.add(comp)
                        db.session.flush()
                        db.session.add(
                            BucketStatus(
                                bucket_id=comp.id, status_code="CLOSED", order=0
                            )
                        )

                        # Archived (placeholder)
                        arch = StatusBucket(
                            name="Archived", department_name="B", order=5, active=True
                        )
                        db.session.add(arch)

                    # Ensure each department has an "Unassigned" bucket so that
                    # dashboard logic can special-case it; admins may override or
                    # edit these via the UI if desired.  We choose order=0 so it
                    # appears before more specific buckets, but admins can adjust
                    # order afterwards.
                    for code in ("A", "B", "C"):
                        existing = StatusBucket.query.filter_by(
                            name="Unassigned", department_name=code
                        ).first()
                        if not existing:
                            ua = StatusBucket(
                                name="Unassigned",
                                department_name=code,
                                order=0,
                                active=True,
                            )
                            db.session.add(ua)

                    db.session.commit()
                    app.logger.info("Seeded default departments and Dept B buckets")
            except Exception:
                app.logger.exception(
                    "Failed to seed default Dept B buckets or departments"
                )

    except Exception:
        # Best-effort; avoid failing app startup if env inspection or imports fail.
        pass

    # Ensure DB session is clean at the end of each request. If an exception
    # occurred during request handling, roll back the session to clear any
    # aborted transaction state so subsequent requests don't fail with
    # "current transaction is aborted" errors.
    @app.teardown_request
    def _teardown_db_session(exc):
        # If an exception occurred during request handling, roll back the
        # session to clear any aborted transaction state. Do NOT call
        # `db.session.remove()` here because some test code expects ORM
        # instances created before a client request to remain refreshable
        # in the test's session. Rolling back is sufficient to return the
        # connection to a clean state without detaching test instances.
        try:
            if exc is not None:
                try:
                    db.session.rollback()
                except Exception:
                    try:
                        app.logger.exception(
                            "Failed to rollback DB session in teardown"
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        except Exception:
            pass

    # Helper context processor: avatar/url helpers and department helper
    @app.context_processor
    def _user_helpers():
        try:
            return dict(
                avatar_url_for=avatar_url_for,
                user_has_multiple_departments=user_has_multiple_departments,
                can_view_metrics_for_user=can_view_metrics_for_user,
                get_user_departments=get_user_departments,
            )
        except Exception:
            return dict(
                avatar_url_for=lambda u, size=34: gravatar_url(None, size),
                user_has_multiple_departments=lambda u: False,
                can_view_metrics_for_user=lambda u: False,
                get_user_departments=lambda u: [],
            )

    @app.cli.command("process-outbox")
    def process_outbox():
        """Process pending integration outbox events (development helper)."""
        try:
            from .services.connector_worker import process_pending_integration_events

            count = process_pending_integration_events(limit=200)
            click.echo(f"Processed {count} integration events")
        except Exception as e:
            click.echo(f"Failed to process outbox: {e}")

    return app
