import os
import hmac
import hashlib
import re
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, current_app, abort, jsonify

from app import csrf
from flask_wtf.csrf import generate_csrf
from ..extensions import db
from ..models import SpecialEmailConfig, User, Request as ReqModel, REQUEST_TYPES, PRIORITIES
from ..models import DepartmentFormAssignment, FormTemplate
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
    recipient = (data.get('to') or '').strip().lower()
    subject = (data.get('subject') or '').strip()
    body = (data.get('body') or data.get('text') or '').strip()

    if not sender:
        current_app.logger.warning('Inbound mail missing sender')
        return (jsonify({'ok': False, 'error': 'missing_sender'}), 400)

    cfg = SpecialEmailConfig.get()

    # Optional mailbox routing guard: resolve explicit request_form_email first,
    # then fall back to configured SSO owner email when available.
    target = None
    if getattr(cfg, 'request_form_email', None):
        target = cfg.request_form_email.strip().lower()
    else:
        try:
            owner_id = int(getattr(cfg, 'request_form_user_id', 0) or 0)
        except Exception:
            owner_id = 0
        if owner_id:
            owner_user = User.query.get(owner_id)
            if owner_user and owner_user.email:
                target = owner_user.email.strip().lower()

    if target:
        if recipient and target not in recipient:
            return jsonify({'ok': True, 'skipped': 'recipient_mismatch'})

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
                ok = None
                if key in ('donor_part_number', 'target_part_number'):
                    ok = inv.validate_part_number(parsed.get(key))
                else:
                    ok = inv.validate_sales_list_number(parsed.get(key))
                if ok is True:
                    checks[key] = True
                elif ok is False:
                    checks[key] = False
                else:
                    checks[key] = None
            except Exception:
                checks[key] = False

    created_request_id = None
    validation_rejected = False
    invalid_fields = []
    out_of_stock_fields = []
    out_of_stock_notified = False
    out_of_stock_notify_mode = None
    if cfg.enabled:
        try:
            sender_norm = sender.lower().strip()
            user = User.query.filter_by(email=sender_norm).first()
            recognized_sso = bool(user and user.sso_sub)

            if recognized_sso:
                desired_dept = (cfg.request_form_department or 'A').upper().strip()
                if desired_dept not in ('A', 'B', 'C'):
                    desired_dept = 'A'
                if user.department != desired_dept:
                    user.department = desired_dept

            req_type_raw = (parsed.get('request_type') or '').strip().lower()
            req_type = req_type_raw or 'both'
            if req_type_raw and req_type_raw not in REQUEST_TYPES:
                invalid_fields.append('request_type')
            if req_type not in REQUEST_TYPES:
                req_type = 'both'

            prio_raw = (parsed.get('priority') or '').strip().lower()
            prio = prio_raw or 'medium'
            if prio_raw and prio_raw not in PRIORITIES:
                invalid_fields.append('priority')
            if prio not in PRIORITIES:
                prio = 'medium'

            sales_list_raw = (parsed.get('sales_list') or parsed.get('pricebook_status') or '').strip().lower()
            sales_list = sales_list_raw or 'unknown'
            if sales_list_raw and sales_list_raw not in ('in_pricebook', 'not_in_pricebook', 'unknown'):
                invalid_fields.append('sales_list')
            if sales_list not in ('in_pricebook', 'not_in_pricebook', 'unknown'):
                sales_list = 'unknown'

            due_at = None
            raw_due = (parsed.get('due_at') or '').strip()
            if raw_due:
                try:
                    due_dt = datetime.fromisoformat(raw_due.replace('Z', '+00:00'))
                    if due_dt.tzinfo is not None:
                        due_dt = due_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    due_at = due_dt
                except Exception:
                    due_at = None
                    invalid_fields.append('due_at')
            if due_at is None:
                due_at = datetime.utcnow() + timedelta(days=2)

            for field_name, is_valid in checks.items():
                if parsed.get(field_name) and is_valid is False:
                    invalid_fields.append(field_name)

            # Verify against admin-edited department form fields when strict mode is enabled.
            strict_validation = bool(getattr(cfg, 'request_form_field_validation_enabled', False))
            dept = (getattr(cfg, 'request_form_department', 'A') or 'A').strip().upper()
            if strict_validation and dept in ('A', 'B', 'C'):
                try:
                    assigned = DepartmentFormAssignment.query.filter_by(department_name=dept).order_by(DepartmentFormAssignment.created_at.desc()).first()
                    template = FormTemplate.query.get(assigned.template_id) if assigned else None
                    if template:
                        template_fields = sorted(list(getattr(template, 'fields', []) or []), key=lambda f: getattr(f, 'created_at', getattr(f, 'id', 0)))
                        for field in template_fields:
                            field_name = (getattr(field, 'name', '') or '').strip()
                            if not field_name:
                                continue
                            field_type = (getattr(field, 'field_type', '') or '').strip().lower()
                            if field_type == 'file':
                                continue

                            value = (parsed.get(field_name) or '').strip()
                            is_required = bool(getattr(field, 'required', False))
                            if is_required and not value:
                                invalid_fields.append(field_name)
                                continue
                            if not value:
                                continue

                            options = [str(getattr(o, 'value', '')).strip() for o in (getattr(field, 'options', []) or []) if str(getattr(o, 'value', '')).strip()]
                            if options and value not in options:
                                invalid_fields.append(field_name)
                                continue

                            verification = getattr(field, 'verification', None) or {}
                            if isinstance(verification, dict) and verification.get('type') == 'regex' and verification.get('pattern'):
                                pattern = str(verification.get('pattern'))
                                if not re.match(pattern, value or ''):
                                    invalid_fields.append(field_name)
                except Exception:
                    current_app.logger.exception('Failed to verify inbound fields against assigned department form template')

            out_of_stock_fields = [
                field_name
                for field_name, is_valid in checks.items()
                if parsed.get(field_name) and is_valid is False
            ]
            notify_on_out_of_stock = bool(getattr(cfg, 'request_form_inventory_out_of_stock_notify_enabled', False))
            if notify_on_out_of_stock and out_of_stock_fields:
                out_of_stock_notify_mode = (getattr(cfg, 'request_form_inventory_out_of_stock_notify_mode', 'email') or 'email').strip().lower()
                if out_of_stock_notify_mode not in ('notification', 'email', 'both'):
                    out_of_stock_notify_mode = 'email'
                out_of_stock_message = getattr(cfg, 'request_form_inventory_out_of_stock_message', None)
                bullet_list = "\n".join([f"- {f}" for f in out_of_stock_fields])
                message_text = (
                    out_of_stock_message.replace('{out_of_stock_fields}', bullet_list)
                    if out_of_stock_message and isinstance(out_of_stock_message, str) and out_of_stock_message.strip()
                    else (
                        "Your request-by-email submission includes inventory fields that are currently out of stock.\n\n"
                        "Out-of-stock field(s):\n"
                        f"{bullet_list}\n\n"
                        "You can continue by updating the parts/values, or wait for inventory restock."
                    )
                )
                try:
                    did_notify = False
                    if out_of_stock_notify_mode in ('notification', 'both') and user is not None:
                        notifications.notify_users(
                            [user],
                            title='Inventory out-of-stock notice',
                            body=message_text,
                            ntype='inventory_out_of_stock',
                            request_id=None,
                            allow_email=False,
                        )
                        db.session.commit()
                        did_notify = True

                    if out_of_stock_notify_mode in ('email', 'both'):
                        email_sent = notifications.send_request_form_inventory_out_of_stock_notice(
                            sender,
                            out_of_stock_fields,
                            message=out_of_stock_message,
                        )
                        did_notify = bool(did_notify or email_sent)

                    out_of_stock_notified = bool(did_notify)
                except Exception:
                    db.session.rollback()
                    out_of_stock_notified = False
                    current_app.logger.exception('Failed to send inbound out-of-stock notification email')

            # Preserve order while removing duplicates
            invalid_fields = list(dict.fromkeys(invalid_fields))
            if strict_validation and invalid_fields:
                validation_rejected = True
                try:
                    notifications.send_request_form_validation_rejection(sender, invalid_fields)
                except Exception:
                    current_app.logger.exception('Failed to send inbound validation rejection email')
                return jsonify({
                    'ok': True,
                    'autoresponder_sent': False,
                    'rejected': True,
                    'invalid_fields': invalid_fields,
                    'out_of_stock_notified': bool(out_of_stock_notified),
                    'out_of_stock_fields': out_of_stock_fields,
                    'out_of_stock_notify_mode': out_of_stock_notify_mode,
                    'parsed': parsed,
                    'checks': checks,
                    'created_request_id': None,
                })

            # Queue autoresponder only when strict validation does not reject the submission.
            try:
                sent = notifications.send_request_form_autoresponder(sender)
            except Exception:
                sent = False

            title = (parsed.get('title') or '').strip() or f"Email request from {sender}"
            description = (parsed.get('description') or '').strip() or body or "Submitted via inbound email."

            req = ReqModel(
                title=title,
                request_type=req_type,
                pricebook_status=sales_list,
                sales_list_reference=(parsed.get('price_book_number') or '').strip() or None,
                description=description,
                priority=prio,
                status='NEW_FROM_A',
                owner_department='B',
                submitter_type='user' if recognized_sso else 'guest',
                created_by_user_id=(user.id if recognized_sso else None),
                guest_email=(None if recognized_sso else sender_norm),
                guest_name=(None if recognized_sso else sender.split('@')[0]),
                due_at=due_at,
            )
            if not recognized_sso:
                req.ensure_guest_token()

            db.session.add(req)
            db.session.commit()
            created_request_id = req.id
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to create request from inbound mail')

    current_app.logger.info('Inbound mail processed', extra={'from': sender, 'subject': subject, 'parsed_keys': list(parsed.keys()), 'checks': checks, 'autoresponder_sent': bool(sent), 'validation_rejected': validation_rejected, 'invalid_fields': invalid_fields, 'out_of_stock_notified': bool(out_of_stock_notified), 'out_of_stock_fields': out_of_stock_fields, 'out_of_stock_notify_mode': out_of_stock_notify_mode, 'created_request_id': created_request_id})

    return jsonify({'ok': True, 'autoresponder_sent': bool(sent), 'rejected': bool(validation_rejected), 'invalid_fields': invalid_fields, 'out_of_stock_notified': bool(out_of_stock_notified), 'out_of_stock_fields': out_of_stock_fields, 'out_of_stock_notify_mode': out_of_stock_notify_mode, 'parsed': parsed, 'checks': checks, 'created_request_id': created_request_id})


@integrations_bp.route('/csrf-token', methods=['GET'])
def csrf_token():
    """Return a fresh CSRF token for API clients.

    Clients should GET this endpoint (it will set the session cookie) and then
    include the token value in the `X-CSRFToken` header for subsequent POSTs.
    """
    token = generate_csrf()
    return jsonify({'csrf_token': token})
