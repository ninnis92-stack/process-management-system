import os
import hmac
import hashlib
from flask import Blueprint, request, current_app, abort, jsonify

from app import csrf
from flask_wtf.csrf import generate_csrf
from .. import notifcations as notifications
from ..services.inventory import InventoryService

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


@integrations_bp.route('/inbound-mail', methods=['POST'])
@csrf.exempt
def inbound_mail():
    """Inbound mail webhook for mail providers (prototype).

    Expected fields (JSON or form):
      - from: sender email
      - to: destination email
      - subject: subject line
      - body: plaintext body

    The endpoint verifies the shared HMAC signature like other webhooks.
    If the configured Request Form feature is enabled, an autoresponder
    will be queued and the subject will be parsed into a key/value map
    using semicolon-separated `key=value` pairs. Inventory checks are
    performed via `InventoryService` where applicable. This handler is
    safe to call even when no inventory connector is configured.
    """
    payload = request.get_data() or b""
    sig = request.headers.get("X-Webhook-Signature") or request.headers.get("X-Signature")
    secret = _get_shared_secret()
    if not secret or not valid_hmac(payload, sig, secret):
        current_app.logger.warning("Inbound mail rejected: invalid/no signature")
        abort(401)

    # Accept JSON or form-encoded payloads
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    sender = (data.get('from') or data.get('sender') or '').strip()
    subject = (data.get('subject') or '').strip()
    body = (data.get('body') or data.get('text') or '').strip()

    if not sender:
        current_app.logger.warning('Inbound mail missing sender')
        return (jsonify({'ok': False, 'error': 'missing_sender'}), 400)

    # Queue autoresponder if feature enabled
    try:
        sent = notifications.send_request_form_autoresponder(sender)
    except Exception:
        sent = False

    # Parse subject into key/value pairs for potential request creation
    parsed = {}
    if subject:
        # Expect format: key1=val1;key2=val2;...
        parts = [p.strip() for p in subject.split(';') if p.strip()]
        for p in parts:
            if '=' in p:
                k, v = p.split('=', 1)
                parsed[k.strip()] = v.strip()

    # Inventory validation for donor/target/price_book_number if present
    inv = InventoryService()
    checks = {}
    for key in ('donor_part_number', 'target_part_number', 'price_book_number'):
        if parsed.get(key):
            try:
                ok = False
                if key in ('donor_part_number', 'target_part_number'):
                    ok = inv.validate_part_number(parsed.get(key))
                else:
                    ok = inv.validate_sales_list_number(parsed.get(key))
                checks[key] = bool(ok)
            except Exception:
                checks[key] = False

    current_app.logger.info('Inbound mail processed', extra={'from': sender, 'subject': subject, 'parsed_keys': list(parsed.keys()), 'checks': checks, 'autoresponder_sent': bool(sent)})

    return jsonify({'ok': True, 'autoresponder_sent': bool(sent), 'parsed': parsed, 'checks': checks})


@integrations_bp.route('/csrf-token', methods=['GET'])
def csrf_token():
    """Return a fresh CSRF token for API clients.

    Clients should GET this endpoint (it will set the session cookie) and then
    include the token value in the `X-CSRFToken` header for subsequent POSTs.
    """
    token = generate_csrf()
    return jsonify({'csrf_token': token})
