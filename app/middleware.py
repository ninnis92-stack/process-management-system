import os
import uuid

from flask import g, request
from werkzeug.middleware.proxy_fix import ProxyFix


def init_runtime_middleware(app):
    """Install request tracing and proxy-aware middleware."""

    if app.config.get("PROXY_FIX_ENABLED"):
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=int(app.config.get("PROXY_FIX_X_FOR", 1)),
            x_proto=int(app.config.get("PROXY_FIX_X_PROTO", 1)),
            x_host=int(app.config.get("PROXY_FIX_X_HOST", 1)),
            x_port=int(app.config.get("PROXY_FIX_X_PORT", 1)),
            x_prefix=int(app.config.get("PROXY_FIX_X_PREFIX", 1)),
        )

    request_id_header = app.config.get("REQUEST_ID_HEADER", "X-Request-ID")

    @app.before_request
    def _attach_request_id():
        incoming = (request.headers.get(request_id_header) or "").strip()
        g.request_id = incoming[:120] if incoming else uuid.uuid4().hex

    @app.after_request
    def _set_request_id_header(response):
        request_id = getattr(g, "request_id", None)
        if request_id:
            response.headers.setdefault(request_id_header, request_id)
        return response


def init_security(app):
    """Install security headers and cookie defaults when enabled.

    Controlled by `SECURITY_HEADERS_ENABLED` env var (default: "False").
    When enabled this sets conservative security headers and adjusts cookie
    settings. The feature is opt-in to avoid breaking prototype workflows.
    """
    enabled = os.getenv("SECURITY_HEADERS_ENABLED", "False").lower() in (
        "1",
        "true",
        "yes",
    )
    if not enabled:
        return

    # Set secure cookie defaults if not explicitly configured
    try:
        app.config.setdefault("SESSION_COOKIE_SECURE", True)
        app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
        app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    except Exception:
        pass

    @app.after_request
    def _set_security_headers(response):
        # HSTS
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload"
        )
        # Clickjacking
        response.headers.setdefault("X-Frame-Options", "DENY")
        # MIME sniffing
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Referrer policy
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        # Basic CSP — opt-in and conservative; adjust per deployment.
        csp = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https:;"
        response.headers.setdefault("Content-Security-Policy", csp)
        return response

    try:
        app.logger.info("Security headers middleware enabled")
    except Exception:
        pass
