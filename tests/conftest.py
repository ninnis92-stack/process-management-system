import os
import warnings
import pytest

try:  # urllib3<2 does not define NotOpenSSLWarning
    from urllib3.exceptions import NotOpenSSLWarning
except Exception:  # noqa: BLE001
    NotOpenSSLWarning = None

from app import create_app
from app.extensions import db
import hashlib

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
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("AUTO_CREATE_DB", "True")

    application = create_app()
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SERVER_NAME="localhost",
    )

    with application.app_context():
        if NotOpenSSLWarning:
            warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope="function")
def client(app):
    return app.test_client()
