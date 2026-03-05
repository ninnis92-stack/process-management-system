import os
import hmac
import hashlib
from flask import Blueprint, request, current_app, abort, jsonify

from app import csrf
from flask_wtf.csrf import generate_csrf

integrations_bp = Blueprint("integrations_bp", __name__, url_prefix="/integrations")


def _get_shared_secret():
    # Prefer app config, then environment variable
    return current_app.config.get("WEBHOOK_SHARED_SECRET") or os.getenv("WEBHOOK_SHARED_SECRET")


def valid_hmac(payload: bytes, signature: str, secret: str) -> bool:
    if not signature or not secret:
        return False
    try:
        # signature expected as hex string; normalize
        sig = signature.strip()
        mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256)
        expected = mac.hexdigest()
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False


@integrations_bp.route("/incoming-webhook", methods=["POST"])
@csrf.exempt
def incoming_webhook():
    """Accepts external POSTs from third-party services.

    This route is intentionally CSRF-exempt; callers MUST present a valid
    HMAC signature in the `X-Webhook-Signature` header. The shared secret is
    looked up from `WEBHOOK_SHARED_SECRET` in app config or env.
    """
    payload = request.get_data() or b""
    sig = request.headers.get("X-Webhook-Signature") or request.headers.get("X-Signature")
    secret = _get_shared_secret()
    if not secret:
        current_app.logger.warning("Incoming webhook rejected: no shared secret configured")
        abort(401)

    if not valid_hmac(payload, sig, secret):
        current_app.logger.warning("Incoming webhook rejected: invalid signature")
        abort(401)

    # At this point the webhook is authenticated. Implement service-specific
    # payload parsing and processing here. Keep processing short or enqueue a
    # background job.
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    # example: log and return 204
    current_app.logger.info("Received webhook: %s", {"headers": dict(request.headers), "json_keys": list(data.keys())})
    return ("", 204)


@integrations_bp.route('/csrf-token', methods=['GET'])
def csrf_token():
    """Return a fresh CSRF token for API clients.

    Clients should GET this endpoint (it will set the session cookie) and then
    include the token value in the `X-CSRFToken` header for subsequent POSTs.
    """
    token = generate_csrf()
    return jsonify({'csrf_token': token})
