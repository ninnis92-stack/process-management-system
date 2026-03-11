import os
from importlib import import_module
from typing import TYPE_CHECKING

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

try:
    _fc = import_module("flask_caching")
    Cache = getattr(_fc, "Cache", None)
except Exception:  # pragma: no cover - optional dependency
    Cache = None

_redis = None
try:
    import redis as _redis
except Exception:
    _redis = None


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


db = SQLAlchemy(session_options={"expire_on_commit": False})
login_manager = LoginManager()
# Cache instance (initialized in app factory if Flask-Caching is available)
cache = Cache() if Cache is not None else None
# Redis client (initialized in app factory if `redis` is available)
redis_client = None
# Instantiate migrate only when the package is present so tests/dev envs
# without Flask-Migrate don't fail at import time.
migrate = Migrate() if Migrate is not None else None


def init_redis_client(app):
    """Initialize a redis client from `REDIS_URL` in app config.

    This is optional; if `REDIS_URL` is not set or the redis package isn't
    available, the function returns None and the app continues running.
    """
    global redis_client
    if _redis is None:
        try:
            app.logger.info("redis package not installed; skipping redis client init")
        except Exception:
            pass
        return None
    try:
        url = app.config.get("REDIS_URL") or os.getenv("REDIS_URL")
        if not url:
            return None
        redis_client = _redis.from_url(url, decode_responses=True)
        try:
            app.logger.info("Redis client initialized")
        except Exception:
            pass
        return redis_client
    except Exception:
        try:
            app.logger.warning("Redis client not initialized")
        except Exception:
            pass
        redis_client = None
        return None


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
            app.logger.warning(
                "Sentry not initialized (missing package or invalid DSN)"
            )
        except Exception:
            pass
        return None


__all__ = [
    "db",
    "login_manager",
    "migrate",
    "init_sentry",
    "cache",
    "init_redis_client",
    "redis_client",
]


def get_or_404(model, id_):
    """Convenience wrapper to replace deprecated ``Model.query.get_or_404``.

    Uses the session-level ``db.session.get(model, id)`` API and aborts with
    a 404 if the object is not found. This keeps callsites tiny and avoids
    depending on the legacy Query.get_or_404 behavior.
    """
    try:
        from flask import abort
    except Exception:
        abort = None
    try:
        obj = db.session.get(model, id_)
    except Exception:
        # If the session is in an aborted state (e.g. an earlier DB error
        # during this request), rollback and attempt the lookup again. This
        # helps avoid cascading "current transaction is aborted" errors and
        # lets callers receive a proper 404 when the object truly doesn't exist.
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            obj = db.session.get(model, id_)
        except Exception:
            obj = None

    if obj is None:
        if abort:
            abort(404)
        raise LookupError("Not found")
    return obj


__all__.append("get_or_404")
