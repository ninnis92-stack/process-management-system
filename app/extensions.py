from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import importlib

# Import Flask-Migrate lazily so missing optional dev deps don't raise static
# import errors in editors. Use importlib to avoid a hard import that some
# linters/IDEs flag when the package isn't installed.
try:
	_fm = importlib.import_module("flask_migrate")
	Migrate = getattr(_fm, "Migrate", None)
except Exception:  # pragma: no cover - optional dependency in dev
	Migrate = None

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate() if Migrate is not None else None