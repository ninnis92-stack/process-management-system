import os
import time
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
        g.request_started_at = time.perf_counter()

    @app.after_request
    def _set_request_id_header(response):
        request_id = getattr(g, "request_id", None)
        if request_id:
            response.headers.setdefault(request_id_header, request_id)

        if app.config.get("REQUEST_LOGGING_ENABLED", True):
            skip_prefixes = app.config.get("REQUEST_LOGGING_SKIP_PATHS", ["/static/"])
            path = request.path or "/"
            if not any(path.startswith(prefix) for prefix in skip_prefixes):
                started_at = getattr(g, "request_started_at", None)
                duration_ms = None
                if started_at is not None:
                    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                try:
                    from flask_login import current_user

                    user_id = (
                        getattr(current_user, "id", None)
                        if getattr(current_user, "is_authenticated", False)
                        else None
                    )
                except Exception:
                    user_id = None

                log_level = "warning"
                if response.status_code < 400:
                    slow_threshold = int(
                        app.config.get("SLOW_REQUEST_THRESHOLD_MS", 750)
                    )
                    log_level = (
                        "info"
                        if duration_ms is None or duration_ms < slow_threshold
                        else "warning"
                    )

                getattr(app.logger, log_level)(
                    "request completed",
                    extra={
                        "request_id": request_id,
                        "method": request.method,
                        "path": path,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                        "user_id": user_id,
                        "remote_addr": request.headers.get(
                            "X-Forwarded-For", request.remote_addr
                        ),
                    },
                )
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
