from authlib.integrations.flask_client import OAuth

oauth = OAuth()

def init_oauth(app):
    oauth.init_app(app)

    if not app.config.get("SSO_ENABLED"):
        return False

    # Ensure required values exist to avoid runtime errors when disabled/misconfigured
    required = ["OIDC_DISCOVERY_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI"]
    if not all(app.config.get(k) for k in required):
        app.logger.warning("SSO_ENABLED but OIDC config missing; skipping OIDC registration")
        return False

    oauth.register(
        name="oidc",
        server_metadata_url=app.config["OIDC_DISCOVERY_URL"],
        client_id=app.config["OIDC_CLIENT_ID"],
        client_secret=app.config["OIDC_CLIENT_SECRET"],
        client_kwargs={"scope": app.config.get("OIDC_SCOPES", "openid email profile")},
    )
    return True


def token_has_mfa(id_token: dict) -> bool:
    """Inspect an OIDC id_token (decoded claims) for MFA/AMR indicators.

    Returns True when the authentication methods (`amr`) include an MFA indicator
    such as 'mfa' or 'otp'. This is a heuristic and depends on the IdP.
    """
    if not id_token:
        return False
    amr = id_token.get("amr") or []
    if isinstance(amr, str):
        amr = [amr]
    for v in amr:
        if v and v.lower() in ("mfa", "otp", "2fa", "hwk"):  # common indicators
            return True
    return False