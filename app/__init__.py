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
from werkzeug.security import generate_password_hash

from con***REMOVED***g import Con***REMOVED***g
from .extensions import db, login_manager, migrate
from flask_wtf import CSRFProtect
from .models import User

# Module-level CSRFProtect instance so other modules can use `from app import csrf`
csrf = CSRFProtect()

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.con***REMOVED***g.from_object(Con***REMOVED***g)

    @app.cli.command("notify-due")
    def notify_due():
        from .noti***REMOVED***cations.due import send_due_soon_noti***REMOVED***cations
        send_due_soon_noti***REMOVED***cations(current_app, hours=24)

    @app.cli.command("create-user")
    @click.option("--email", required=True, help="User email")
    @click.option("--name", default=None, help="Display name")
    @click.option("--department", default="A", type=click.Choice(["A", "B", "C"], case_sensitive=False))
    @click.option("--password", default="password123", help="Password for local login")
    def create_user_cli(email, name, department, password):
        """Create a local user (dev/test)."""
        email_n = email.strip().lower()
        with app.app_context():
            existing = User.query.***REMOVED***lter_by(email=email_n).***REMOVED***rst()
            if existing:
                click.echo(f"User {email_n} already exists; updating department/name/password")
                existing.department = department.upper()
                existing.name = name or existing.name
                existing.password_hash = generate_password_hash(password)
                existing.is_active = True
                db.session.commit()
                return
            u = User(
                email=email_n,
                name=name,
                department=department.upper(),
                password_hash=generate_password_hash(password),
                is_active=True,
            )
            db.session.add(u)
            db.session.commit()
            click.echo(f"Created {email_n} in Dept {department.upper()}")

    # Init OAuth (SSO)
    from .auth.sso import init_oauth
    init_oauth(app)

    # Upload folder (best-effort; serverless may not allow writes)
    upload_folder = app.con***REMOVED***g.get("UPLOAD_FOLDER")
    if upload_folder:
        try:
            os.makedirs(upload_folder, exist_ok=True)
        except OSError:
            pass

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    # Enable CSRF protection for all forms (create module-level instance so
    # individual routes can be exempted when necessary)
    from . import csrf as _csrf  # local import to ensure module-level var exists
    _csrf.init_app(app)

    # Initialize Flask-Migrate (Alembic) for DB migrations if available
    try:
        if migrate is not None:
            migrate.init_app(app, db)
    except Exception:
        # If Flask-Migrate isn't installed in this environment, skip init
        pass

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    # Apply impersonation override on each request: if an admin has started an
    # acting-as session, temporarily present them as a member of the target dept.
    @app.before_request
    def _apply_impersonation():
        from flask_login import current_user
        try:
            if not current_user or not getattr(current_user, 'is_authenticated', False):
                return
        except Exception:
            return

        imp_admin = None
        from flask import session as _session
        imp_admin = _session.get('impersonate_admin_id')
        imp_dept = _session.get('impersonate_dept')
        if imp_admin and imp_dept and int(imp_admin) == int(getattr(current_user, 'id', -1)):
            # Override department for permission checks and templates for duration of request.
            try:
                current_user.department = imp_dept
                current_user.is_acting_as = True
                current_user.act_as_label = f"Acting as Dept {imp_dept}"
            except Exception:
                pass

    from .auth.routes import auth_bp
    from .requests_bp.routes import requests_bp
    from .external.routes import external_bp
    from .noti***REMOVED***cations.routes import noti***REMOVED***cations_bp
    from .admin.routes import admin_bp
    from .integrations.webhooks import integrations_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(external_bp)
    app.register_blueprint(noti***REMOVED***cations_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(integrations_bp)

    # DEV ONLY: auto-create tables
    if os.getenv("AUTO_CREATE_DB", "True") == "True":
        with app.app_context():
            db.create_all()

    return app