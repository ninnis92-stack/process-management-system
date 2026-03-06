from importlib import import_module
from typing import TYPE_CHECKING

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager


if TYPE_CHECKING:
	# Statically import optional packages for editor/type-checker visibility.
	try:  # pragma: no cover - editor-only
		import sentry_sdk  # type: ignore
		from sentry_sdk.integrations.flask import FlaskIntegration  # type: ignore
	except Exception:  # pragma: no cover - editor-only
		pass


# Import Flask-Migrate lazily so missing optional dev deps don't raise static
# import errors in editors.
try:
	_fm = import_module("flask_migrate")
	Migrate = getattr(_fm, "Migrate", None)
except Exception:  # pragma: no cover - optional dependency in dev
	Migrate = None


db = SQLAlchemy()
login_manager = LoginManager()
# Instantiate migrate only when the package is present so tests/dev envs
# without Flask-Migrate don't fail at import time.
migrate = Migrate() if Migrate is not None else None


def init_sentry(app):
	"""Initialize Sentry SDK if `SENTRY_DSN` is configured.

	This function is optional and fails gracefully when `sentry-sdk` is
	not installed or `SENTRY_DSN` is not set. Call from the application
	factory after `app.config` is loaded.
	"""
	try:
		dsn = app.config.get("SENTRY_DSN")
		if not dsn:
			return None
		# Import lazily via importlib so environments without sentry-sdk won't fail
		# and editors/type-checkers won't require the package to be installed.
		try:
			_sentry = import_module("sentry_sdk")
			_si = import_module("sentry_sdk.integrations.flask")
			_FlaskIntegration = getattr(_si, "FlaskIntegration", None)
		except Exception:
			_sentry = None
			_FlaskIntegration = None

		if _sentry is None:
			# Sentry not installed; skip initialization.
			return None

		integrations = [_FlaskIntegration()] if _FlaskIntegration is not None else []
		_sentry.init(
			dsn=dsn,
			environment=app.config.get("SENTRY_ENVIRONMENT"),
			integrations=integrations,
		)
		try:
			app.logger.info("Sentry initialized")
		except Exception:
			pass
		return True
	except Exception:
		# If Sentry isn't installed or init failed, log and continue.
		try:
			app.logger.warning("Sentry not initialized (missing package or invalid DSN)")
		except Exception:
			pass
		return None


__all__ = ["db", "login_manager", "migrate", "init_sentry"]