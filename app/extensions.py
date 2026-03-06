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


def init_sentry(app):
	"""Initialize Sentry SDK if `SENTRY_DSN` is configured.

	This function is optional and fails gracefully when `sentry-sdk` is
	not installed or `SENTRY_DSN` is not set. Call from the application
	factory after `app.config` is loaded.
	"""
	try:
		dsn = app.config.get('SENTRY_DSN') or None
		if not dsn:
			return None
		# Import lazily so environments without sentry-sdk won't fail.
		import sentry_sdk
		from sentry_sdk.integrations.flask import FlaskIntegration
		sentry_sdk.init(dsn=dsn, environment=app.config.get('SENTRY_ENVIRONMENT'), integrations=[FlaskIntegration()])
		app.logger.info('Sentry initialized')
		return True
	except Exception:
		# If Sentry isn't installed or init failed, log and continue.
		try:
			app.logger.warning('Sentry not initialized (missing package or invalid DSN)')
		except Exception:
			pass
		return None