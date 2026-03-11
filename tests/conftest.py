import os
import warnings

import pytest

try:  # urllib3<2 does not define NotOpenSSLWarning
    from urllib3.exceptions import NotOpenSSLWarning
except Exception:  # noqa: BLE001
    NotOpenSSLWarning = None

import hashlib

from app import create_app
from app.extensions import db

# Some Python environments (notably older macOS builds) may not expose hashlib.scrypt.
# Werkzeug's generate_password_hash uses scrypt by default; provide a lightweight
# fallback that maps scrypt calls to pbkdf2_hmac so tests can run in CI/dev envs.
if not hasattr(hashlib, "scrypt"):

    def _scrypt_fallback(password, *, salt, n, r, p, maxmem=None):
        # Use pbkdf2_hmac as a conservative fallback; parameters won't match
        # scrypt's semantics but are sufficient for tests that only need a hash.
        return hashlib.pbkdf2_hmac("sha256", password, salt, 100000)

    hashlib.scrypt = _scrypt_fallback


@pytest.fixture(scope="function")
def app(monkeypatch):
    # To avoid the per-connection isolation of SQLite in-memory databases we
    # instead use a temporary file-backed database for each test.  This ensures
    # that client requests, teardown hooks, and the test harness all see the
    # same data without worrying about pooling behavior.  The temporary file is
    # removed when the fixture completes.
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setenv("AUTO_CREATE_DB", "True")

    application = create_app()
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SERVER_NAME="localhost",
        RATE_LIMIT_ENABLED=False,  # disable global rate limits during tests
    )
    # store the path on the app so the teardown block can remove it later
    application._test_sqlite_path = path

    # The `poolclass` setting must be interpreted by SQLAlchemy; the simple
    # string above is converted to StaticPool in the app factory so we don't
    # have to import it here and risk circular imports.  (The factory handles
    # this pattern elsewhere.)

    with application.app_context():
        if NotOpenSSLWarning:
            warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()
    # cleanup the temporary sqlite file
    try:
        os.unlink(application._test_sqlite_path)
    except Exception:
        pass


@pytest.fixture(scope="function")
def client(app):
    return app.test_client()
