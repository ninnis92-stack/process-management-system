import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    if not SQLALCHEMY_DATABASE_URI:
        # local default
        SQLALCHEMY_DATABASE_URI = "sqlite:///app.db"

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-fallback")
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/data/uploads")

    # SSO / OIDC (all optional; guarded by SSO_ENABLED)
    SSO_ENABLED = os.getenv("SSO_ENABLED", "False") == "True"
    OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID")
    OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET")
    OIDC_DISCOVERY_URL = os.getenv("OIDC_DISCOVERY_URL")
    OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI")
    OIDC_LOGOUT_URL = os.getenv("OIDC_LOGOUT_URL")  # optional
    OIDC_SCOPES = os.getenv("OIDC_SCOPES", "openid email profile")
    SSO_FALLBACK_LOCAL = os.getenv("SSO_FALLBACK_LOCAL", "True") == "True"

    # Uploads (note: not durable on Vercel)
    _default_upload_folder = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
    MAX_FILES_PER_SUBMISSION = 10
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
    DISABLE_UPLOADS = os.getenv("DISABLE_UPLOADS", "False") == "True"

    # For serverless environments, allow overriding the upload folder to a writable location
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(BASE_DIR, "uploads"))

    # Part number validation (future integration)
    PART_API_ENABLED = os.getenv("PART_API_ENABLED", "False") == "True"
    PART_API_URL = os.getenv("PART_API_URL")  # e.g., https://parts.example.com/api/validate
    PART_API_TOKEN = os.getenv("PART_API_TOKEN")
    PART_API_TIMEOUT = int(os.getenv("PART_API_TIMEOUT", "5"))

    # Method verification (separate service allowing different endpoints/tokens)
    METHOD_API_ENABLED = os.getenv("METHOD_API_ENABLED", "False") == "True"
    METHOD_API_URL = os.getenv("METHOD_API_URL")
    METHOD_API_TOKEN = os.getenv("METHOD_API_TOKEN")
    METHOD_API_TIMEOUT = int(os.getenv("METHOD_API_TIMEOUT", "5"))

    # Email settings (prototype-friendly defaults)
    EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "False") == "True"
    EMAIL_FROM = os.getenv("EMAIL_FROM", "no-reply@example.com")
    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = os.getenv("SMTP_PORT")
    SMTP_USERNAME = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "False") == "True"
    SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "10"))

    # External ticketing integration (prototype mode returns fake ticket ids)
    TICKETING_ENABLED = os.getenv("TICKETING_ENABLED", "False") == "True"
    TICKETING_URL = os.getenv("TICKETING_URL")
    TICKETING_TOKEN = os.getenv("TICKETING_TOKEN")
    TICKETING_TIMEOUT = int(os.getenv("TICKETING_TIMEOUT", "5"))

    # Test email handling: comma-separated domains to treat as test accounts (skip real SMTP sends)
    TEST_EMAIL_DOMAINS = [d.strip().lower() for d in os.getenv("TEST_EMAIL_DOMAINS", "example.com,example.org").split(",") if d.strip()]

    # Admin users allowed to access the internal admin UI (comma-separated emails)
    ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
    # Session cookie hardening recommended for production
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "True") == "True"
    SESSION_COOKIE_HTTPONLY = os.getenv("SESSION_COOKIE_HTTPONLY", "True") == "True"
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    # WTForms/CSRF settings
    # Increase CSRF token lifetime for prototype use (default 24 hours)
    WTF_CSRF_TIME_LIMIT = int(os.getenv("WTF_CSRF_TIME_LIMIT", "86400"))
