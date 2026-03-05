import os
import warnings
import pytest

try:  # urllib3<2 does not define NotOpenSSLWarning
    from urllib3.exceptions import NotOpenSSLWarning
except Exception:  # noqa: BLE001
    NotOpenSSLWarning = None

from app import create_app
from app.extensions import db


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
