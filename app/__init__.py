import os
from dotenv import load_dotenv
from flask import Flask

from con***REMOVED***g import Con***REMOVED***g
from .extensions import db, login_manager
from .models import User

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.con***REMOVED***g.from_object(Con***REMOVED***g)

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