import os

BASE_DIR = os.path.abspath(os.path.dirname(__***REMOVED***le__))

class Con***REMOVED***g:
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
    OIDC_SCOPES = os.getenv("OIDC_SCOPES", "openid email pro***REMOVED***le")
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
