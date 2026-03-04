import os
import click
from dotenv import load_dotenv
from flask import Flask, current_app
from werkzeug.security import generate_password_hash

from con***REMOVED***g import Con***REMOVED***g
from .extensions import db, login_manager
from .models import User

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

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    from .auth.routes import auth_bp
    from .requests_bp.routes import requests_bp
    from .external.routes import external_bp
    from .noti***REMOVED***cations.routes import noti***REMOVED***cations_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(external_bp)
    app.register_blueprint(noti***REMOVED***cations_bp)

    # DEV ONLY: auto-create tables
    if os.getenv("AUTO_CREATE_DB", "True") == "True":
        with app.app_context():
            db.create_all()

    return app