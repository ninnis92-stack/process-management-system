from flask import current_app, session
from flask_login import current_user

from ..services.tenant_context import user_has_permission


def _is_admin_user() -> bool:
    """Return ``True`` if the current user should see admin pages.

    This mirrors the logic previously embedded in ``routes.py`` but
    lives in a shared location so other modules (e.g. new tenant
    handlers) can call it without pulling in the huge monolithic
    ``routes.py`` file.
    """
    if not current_user.is_authenticated:
        return False
    if not (getattr(current_user, "is_admin", False) or user_has_permission(current_user, "admin")):
        return False

    if current_app.config.get("SSO_ENABLED") and current_app.config.get(
        "SSO_REQUIRE_MFA"
    ):
        return bool(session.get("sso_mfa", False))

    return True
