from authlib.integrations.flask_client import OAuth

oauth = OAuth()

def init_oauth(app):
    oauth.init_app(app)

    if not app.con***REMOVED***g.get("SSO_ENABLED"):
        return False

    # Ensure required values exist to avoid runtime errors when disabled/miscon***REMOVED***gured
    required = ["OIDC_DISCOVERY_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI"]
    if not all(app.con***REMOVED***g.get(k) for k in required):
        app.logger.warning("SSO_ENABLED but OIDC con***REMOVED***g missing; skipping OIDC registration")
        return False

    oauth.register(
        name="oidc",
        server_metadata_url=app.con***REMOVED***g["OIDC_DISCOVERY_URL"],
        client_id=app.con***REMOVED***g["OIDC_CLIENT_ID"],
        client_secret=app.con***REMOVED***g["OIDC_CLIENT_SECRET"],
        client_kwargs={"scope": app.con***REMOVED***g.get("OIDC_SCOPES", "openid email pro***REMOVED***le")},
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