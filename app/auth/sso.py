from typing import Optional

from authlib.integrations.flask_client import OAuth

oauth = OAuth()


def init_oauth(app):
    oauth.init_app(app)

    if not app.config.get("SSO_ENABLED"):
        return False

    # Ensure required values exist to avoid runtime errors when disabled/misconfigured
    required = [
        "OIDC_DISCOVERY_URL",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET",
        "OIDC_REDIRECT_URI",
    ]
    if not all(app.config.get(k) for k in required):
        app.logger.warning(
            "SSO_ENABLED but OIDC config missing; skipping OIDC registration"
        )
        return False

    oauth.register(
        name="oidc",
        server_metadata_url=app.config["OIDC_DISCOVERY_URL"],
        client_id=app.config["OIDC_CLIENT_ID"],
        client_secret=app.config["OIDC_CLIENT_SECRET"],
        client_kwargs={"scope": app.config.get("OIDC_SCOPES", "openid email profile")},
    )
    return True


def token_has_mfa(id_token: dict, config: Optional[dict] = None) -> bool:
    """Inspect an OIDC id_token (decoded claims) for MFA/AMR indicators.

    Returns True when the authentication methods (`amr`) include an MFA indicator
    such as 'mfa' or 'otp'. This is a heuristic and depends on the IdP.
    """
    if not id_token:
        return False
    cfg = config or {}
    claim_path = cfg.get("SSO_MFA_CLAIM", "amr")
    expected = set(cfg.get("SSO_MFA_CLAIM_VALUES", ["mfa", "otp", "2fa", "hwk"]) or [])
    raw = _get_nested_claim(id_token, claim_path)
    actual = set(_normalize_claim_values(raw))
    if actual & expected:
        return True

    # Backwards-compatible fallback to `amr` common indicators.
    amr = id_token.get("amr") or []
    if isinstance(amr, str):
        amr = [amr]
    for v in amr:
        if v and v.lower() in ("mfa", "otp", "2fa", "hwk"):
            return True
    return False


def _get_nested_claim(claims: dict, claim_path: str):
    """Resolve a nested claim path like `roles` or `realm_access.roles`."""
    if not claims or not claim_path:
        return None
    cur = claims
    for part in [p.strip() for p in claim_path.split(".") if p.strip()]:
        if isinstance(cur, dict) and part in cur:
            cur = cur.get(part)
        else:
            return None
    return cur


def _normalize_claim_values(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip().lower() for v in value if str(v).strip()]
    return [str(value).strip().lower()] if str(value).strip() else []


def sso_user_is_admin(userinfo: dict, config: dict, email: str = "") -> bool:
    """Determine whether an SSO-authenticated user should be treated as admin.

    Sources checked:
    - `SSO_ADMIN_EMAILS`
    - `ADMIN_EMAILS`
    - configured claim path/value pair (`SSO_ADMIN_CLAIM`, `SSO_ADMIN_CLAIM_VALUES`)
    """
    email_n = (email or userinfo.get("email") or "").strip().lower()
    configured_emails = set(config.get("SSO_ADMIN_EMAILS", []) or []) | set(
        config.get("ADMIN_EMAILS", []) or []
    )
    if email_n and email_n in configured_emails:
        return True

    if not config.get("SSO_ADMIN_SYNC_ENABLED", True):
        return False

    claim_path = config.get("SSO_ADMIN_CLAIM")
    expected = set(config.get("SSO_ADMIN_CLAIM_VALUES", []) or [])
    if not claim_path or not expected:
        return False

    actual = set(_normalize_claim_values(_get_nested_claim(userinfo, claim_path)))
    return bool(actual & expected)
