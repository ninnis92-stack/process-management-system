import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    if not SQLALCHEMY_DATABASE_URI:
        # local default
        SQLALCHEMY_DATABASE_URI = "sqlite:///app.db"

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-fallback")
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/data/uploads")
    REQUEST_ID_HEADER = os.getenv("REQUEST_ID_HEADER", "X-Request-ID")
    REQUEST_LOGGING_ENABLED = (
        os.getenv("REQUEST_LOGGING_ENABLED", "True") == "True"
    )
    REQUEST_LOGGING_SKIP_PATHS = [
        p.strip()
        for p in os.getenv("REQUEST_LOGGING_SKIP_PATHS", "/static/").split(",")
        if p.strip()
    ]
    SLOW_REQUEST_THRESHOLD_MS = int(os.getenv("SLOW_REQUEST_THRESHOLD_MS", "750"))
    RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "True") == "True"
    LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5/300")
    GUEST_LOOKUP_RATE_LIMIT = os.getenv("GUEST_LOOKUP_RATE_LIMIT", "10/300")
    GUEST_SUBMIT_RATE_LIMIT = os.getenv("GUEST_SUBMIT_RATE_LIMIT", "5/300")
    GUEST_COMMENT_RATE_LIMIT = os.getenv("GUEST_COMMENT_RATE_LIMIT", "10/300")
    WEBHOOK_RATE_LIMIT = os.getenv("WEBHOOK_RATE_LIMIT", "60/60")
    PREFERRED_URL_SCHEME = os.getenv("PREFERRED_URL_SCHEME", "http")
    PROXY_FIX_ENABLED = os.getenv("PROXY_FIX_ENABLED", "False") == "True"
    PROXY_FIX_X_FOR = int(os.getenv("PROXY_FIX_X_FOR", "1"))
    PROXY_FIX_X_PROTO = int(os.getenv("PROXY_FIX_X_PROTO", "1"))
    PROXY_FIX_X_HOST = int(os.getenv("PROXY_FIX_X_HOST", "1"))
    PROXY_FIX_X_PORT = int(os.getenv("PROXY_FIX_X_PORT", "1"))
    PROXY_FIX_X_PREFIX = int(os.getenv("PROXY_FIX_X_PREFIX", "1"))
    SECURITY_HEADERS_ENABLED = os.getenv("SECURITY_HEADERS_ENABLED", "False") == "True"
    HEALTHCHECK_REDIS_REQUIRED = (
        os.getenv("HEALTHCHECK_REDIS_REQUIRED", "False") == "True"
    )
    HEALTHCHECK_INCLUDE_DETAILS = (
        os.getenv("HEALTHCHECK_INCLUDE_DETAILS", "True") == "True"
    )
    WEBHOOK_REQUIRE_TIMESTAMP = (
        os.getenv("WEBHOOK_REQUIRE_TIMESTAMP", "False") == "True"
    )
    WEBHOOK_SIGNATURE_TTL_SECONDS = int(
        os.getenv("WEBHOOK_SIGNATURE_TTL_SECONDS", "300")
    )
    WEBHOOK_REPLAY_PROTECTION_ENABLED = (
        os.getenv("WEBHOOK_REPLAY_PROTECTION_ENABLED", "True") == "True"
    )
    TENANT_REQUIRED = os.getenv("TENANT_REQUIRED", "True") == "True"
    PLAN_ENFORCEMENT_ENABLED = os.getenv("PLAN_ENFORCEMENT_ENABLED", "True") == "True"
    RQ_ENABLED = os.getenv("RQ_ENABLED", "False") == "True"

    # Debugging convenience: allow an admin to "impersonate" another
    # department (or specific user) from the UI.  The routes and UI are
    # present but the feature is off by default; set
    # `ALLOW_IMPERSONATION=True` in your environment to enable it.
    ALLOW_IMPERSONATION = os.getenv("ALLOW_IMPERSONATION", "False") == "True"

    # SSO / OIDC (all optional; guarded by SSO_ENABLED)
    SSO_ENABLED = os.getenv("SSO_ENABLED", "False") == "True"
    OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID")
    OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET")
    OIDC_DISCOVERY_URL = os.getenv("OIDC_DISCOVERY_URL")
    OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI")
    OIDC_LOGOUT_URL = os.getenv("OIDC_LOGOUT_URL")  # optional
    OIDC_SCOPES = os.getenv("OIDC_SCOPES", "openid email profile")
    SSO_FALLBACK_LOCAL = os.getenv("SSO_FALLBACK_LOCAL", "True") == "True"
    # Sync admin permissions from organization-managed SSO claims/groups.
    # Example:
    #   SSO_ADMIN_SYNC_ENABLED=True
    #   SSO_ADMIN_CLAIM=groups
    #   SSO_ADMIN_CLAIM_VALUES=app-admin,process-admins
    #   SSO_ADMIN_SYNC_STRICT=True
    SSO_ADMIN_SYNC_ENABLED = os.getenv("SSO_ADMIN_SYNC_ENABLED", "True") == "True"
    SSO_ADMIN_SYNC_STRICT = os.getenv("SSO_ADMIN_SYNC_STRICT", "False") == "True"
    SSO_ADMIN_CLAIM = os.getenv("SSO_ADMIN_CLAIM", "roles")
    SSO_ADMIN_CLAIM_VALUES = [
        v.strip().lower()
        for v in os.getenv("SSO_ADMIN_CLAIM_VALUES", "admin").split(",")
        if v.strip()
    ]
    # Optional explicit SSO-admin email allow-list, in addition to ADMIN_EMAILS.
    SSO_ADMIN_EMAILS = [
        e.strip().lower()
        for e in os.getenv("SSO_ADMIN_EMAILS", "").split(",")
        if e.strip()
    ]
    # Optional primary-department sync from SSO claims.
    # Example:
    #   SSO_DEPARTMENT_SYNC_ENABLED=True
    #   SSO_DEPARTMENT_CLAIM=department
    #   SSO_DEPARTMENT_MAP=sales:A,ops:B,quality:C
    SSO_DEPARTMENT_SYNC_ENABLED = (
        os.getenv("SSO_DEPARTMENT_SYNC_ENABLED", "False") == "True"
    )
    SSO_DEPARTMENT_CLAIM = os.getenv("SSO_DEPARTMENT_CLAIM", "department")
    SSO_DEPARTMENT_MAP = {
        key.strip().lower(): value.strip().upper()
        for key, value in (
            pair.split(":", 1)
            for pair in os.getenv("SSO_DEPARTMENT_MAP", "").split(",")
            if ":" in pair
        )
        if key.strip() and value.strip()
    }
    # Optional MFA enforcement for SSO-backed admin access.
    SSO_REQUIRE_MFA = os.getenv("SSO_REQUIRE_MFA", "False") == "True"
    SSO_MFA_CLAIM = os.getenv("SSO_MFA_CLAIM", "amr")
    SSO_MFA_CLAIM_VALUES = [
        v.strip().lower()
        for v in os.getenv("SSO_MFA_CLAIM_VALUES", "mfa,otp,2fa,hwk").split(",")
        if v.strip()
    ]

    # Uploads (ensure upload folder is durable in production)
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
    PART_API_URL = os.getenv(
        "PART_API_URL"
    )  # e.g., https://parts.example.com/api/validate
    PART_API_TOKEN = os.getenv("PART_API_TOKEN")
    PART_API_TIMEOUT = int(os.getenv("PART_API_TIMEOUT", "5"))

    # External verification feature flag (safe to keep False until migrations/connectors ready)
    ENABLE_EXTERNAL_VERIFICATION = (
        os.getenv("ENABLE_EXTERNAL_VERIFICATION", "False") == "True"
    )

    # Inventory connector (skeleton). When False the InventoryService is a no-op.
    INVENTORY_ENABLED = os.getenv("INVENTORY_ENABLED", "False") == "True"
    INVENTORY_DSN = os.getenv("INVENTORY_DSN")

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
    TEST_EMAIL_DOMAINS = [
        d.strip().lower()
        for d in os.getenv("TEST_EMAIL_DOMAINS", "example.com,example.org").split(",")
        if d.strip()
    ]

    # Admin users allowed to access the internal admin UI (comma-separated emails)
    ADMIN_EMAILS = [
        e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()
    ]
    # Session cookies should remain non-secure by default for local HTTP
    # development. Production deployments should set SESSION_COOKIE_SECURE=True.
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False") == "True"
    SESSION_COOKIE_HTTPONLY = os.getenv("SESSION_COOKIE_HTTPONLY", "True") == "True"
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    # WTForms/CSRF settings
    # Increase CSRF token lifetime for prototype use (default 24 hours)
    WTF_CSRF_TIME_LIMIT = int(os.getenv("WTF_CSRF_TIME_LIMIT", "86400"))
    # When True, tighten request visibility so users only see requests owned
    # by their department or explicitly handed off to them. Useful for
    # enforcing strict inter-department isolation in production.
    ENFORCE_DEPT_ISOLATION = os.getenv("ENFORCE_DEPT_ISOLATION", "False") == "True"

    # Database engine/pool tuning for production. These values can be
    # overridden via environment variables to suit your hosting provider.
    # Example: set `DB_POOL_SIZE=10` and `DB_MAX_OVERFLOW=20` for moderate load.
    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    DB_POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", "True") == "True"

    # Apply engine options for SQLAlchemy (Flask-SQLAlchemy 3.x supports
    # passing `SQLALCHEMY_ENGINE_OPTIONS` dict to control the underlying
    # engine/pool behavior). Avoid passing pool params for SQLite (in-memory
    # or file-based) because many pool implementations reject those args.
    if SQLALCHEMY_DATABASE_URI and not SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": DB_POOL_SIZE,
            "max_overflow": DB_MAX_OVERFLOW,
            "pool_pre_ping": DB_POOL_PRE_PING,
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {}

    # Redis connection URL used for caching and background queues. If not
    # provided, the app will continue running without cache (graceful).
    REDIS_URL = os.getenv("REDIS_URL")

    # Flask-Caching defaults
    CACHE_DEFAULT_TIMEOUT = int(os.getenv("CACHE_DEFAULT_TIMEOUT", "300"))

    @classmethod
    def validate(cls, app=None):
        """Perform sanity checks on configuration values.

        When running in production, the application can call this during
        startup or via the ``flask check-config`` CLI command to catch
        missing/invalid environment variables early.  The method returns a
        list of human-readable error strings; callers may raise or exit based
        on the result.  ``app`` is optional and is used only for logging.
        """
        errors = []
        # basic secrets
        if cls.SECRET_KEY == "dev-fallback":
            errors.append("SECRET_KEY is using the insecure default; set a strong secret in production")

        # SSO/OIDC
        if cls.SSO_ENABLED:
            for key in ("OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_DISCOVERY_URL", "OIDC_REDIRECT_URI"):
                if not getattr(cls, key, None):
                    errors.append(f"{key} must be set when SSO_ENABLED is True")
            # optionally warn if SSO_ADMIN_SYNC_* flags are inconsistent
            if cls.SSO_ADMIN_SYNC_ENABLED and not cls.SSO_ADMIN_CLAIM:
                errors.append("SSO_ADMIN_CLAIM cannot be empty when SSO_ADMIN_SYNC_ENABLED is True")

        # email
        if cls.EMAIL_ENABLED:
            if not cls.SMTP_HOST:
                errors.append("SMTP_HOST is required when EMAIL_ENABLED is True")
            if not cls.SMTP_PORT:
                errors.append("SMTP_PORT is required when EMAIL_ENABLED is True")

        # ticketing
        if cls.TICKETING_ENABLED:
            if not cls.TICKETING_URL:
                errors.append("TICKETING_URL is required when TICKETING_ENABLED is True")
            if not cls.TICKETING_TOKEN:
                errors.append("TICKETING_TOKEN is required when TICKETING_ENABLED is True")

        # Redis/DB
        if cls.RATE_LIMIT_ENABLED and not cls.REDIS_URL:
            errors.append("RATE_LIMIT_ENABLED is True but REDIS_URL is not configured")

        # general advice
        if cls.CACHE_DEFAULT_TIMEOUT <= 0:
            errors.append("CACHE_DEFAULT_TIMEOUT must be positive")

        if app and errors:
            for e in errors:
                app.logger.error("Config validation: %s", e)
        return errors
