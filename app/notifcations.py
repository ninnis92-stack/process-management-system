"""In-app notification utilities and email delivery helpers.

This module persists `Notification` rows in the DB and attempts to send
emails to users. In development the code falls back to a thread-based
background sender; when `RQ_ENABLED` and `REDIS_URL` are configured the
send will be enqueued to RQ so a separate worker can process deliveries.

Keep the send path idempotent and non-blocking from request handlers.
"""

from .extensions import db
from .models import Notification, User, SpecialEmailConfig, NotificationRetention
from flask import current_app
from threading import Thread
from typing import Optional

from .services.emailer import EmailService
import importlib

# Use importlib to import optional dependencies at runtime. Add explicit Pylance
# suppression on the dynamic import calls so editors that don't have the optional
# packages installed won't report `reportMissingImports`.
try:
    _redis_mod = importlib.import_module("redis")  # type: ignore[reportMissingImports]
    Redis = getattr(_redis_mod, "Redis", None)
except Exception:  # pragma: no cover - Redis optional for dev
    Redis = None

try:
    _rq_mod = importlib.import_module("rq")  # type: ignore[reportMissingImports]
    Queue = getattr(_rq_mod, "Queue", None)
except Exception:  # pragma: no cover - RQ optional for dev
    Queue = None

try:
    _tasks_mod = importlib.import_module("app.tasks")  # type: ignore[reportMissingImports]
    send_emails_task = getattr(_tasks_mod, "send_emails_task", None)
except Exception:  # pragma: no cover - tasks module may be unavailable to static checker
    send_emails_task = None


def users_in_department(dept: str):
    return User.query.filter_by(department=dept, is_active=True).all()


def _send_emails_async(recipients_map, subject, body, html=None, request_id=None):
    """Send emails in background.

    recipients_map: dict mapping email -> user_id (or None)
    """
    from flask import current_app as _current
    try:
        app = _current._get_current_object()
    except Exception:
        app = None

    # If RQ (Redis Queue) is enabled and configured, enqueue the send task.
    rq_enabled = False
    redis_url = None
    if app:
        rq_enabled = bool(app.config.get("RQ_ENABLED", False))
        redis_url = app.config.get("REDIS_URL") or app.config.get("RQ_REDIS_URL")

    if rq_enabled and redis_url:
        try:
            conn = Redis.from_url(redis_url)
            q = Queue("emails", connection=conn)
            q.enqueue(send_emails_task, recipients_map, subject, body, html, request_id)
            return
        except Exception:
            try:
                _current.logger.exception("Failed to enqueue email send job; falling back to thread")
            except Exception:
                pass

    # Fallback: run in a background thread using captured app context (dev-safe)
    def _send():
        if app is None:
            try:
                _current.logger.warning("Email send skipped: no app context available for background thread")
            except Exception:
                pass
            return

        with app.app_context():
            try:
                svc = EmailService()
                emails = list(recipients_map.keys())
                res = svc.send_email(emails, subject, body, html=html)

                skipped = res.get("skipped") or []
                error = res.get("error")

                for e in skipped:
                    uid = recipients_map.get(e)
                    if uid:
                        db.session.add(Notification(
                            user_id=uid,
                            request_id=request_id,
                            type="email_skipped",
                            title="Email skipped (test account)",
                            body=f"Email to {e} skipped because it is in the test domains.",
                            url=None,
                        ))

                if error:
                    for e, uid in recipients_map.items():
                        if uid:
                            db.session.add(Notification(
                                user_id=uid,
                                request_id=request_id,
                                type="email_failed",
                                title="Email delivery failed",
                                body=f"Email delivery to {e} failed: {error}",
                                url=None,
                            ))

                if (skipped or error):
                    try:
                        db.session.commit()
                    except Exception:
                        _current.logger.exception("Failed to commit email-send notifications")

            except Exception:
                _current.logger.exception("Email sending failed")

    Thread(target=_send, daemon=True).start()


def notify_users(users, title, body=None, url=None, ntype="generic", request_id=None, allow_email: bool = True):
    # Decide whether to persist in-app notifications per-recipient.
    # If the app's EmailService is enabled and an email address exists for
    # a recipient, prefer sending email and skip creating an in-app row for
    # that recipient. This prevents duplicate delivery paths once email
    # integration is active. Users without email addresses will still
    # receive in-app notifications.
    recipients_map = {}
    try:
        svc = EmailService()
        email_enabled = bool(getattr(svc, "enabled", False))
    except Exception:
        email_enabled = False

    for u in users:
        has_email = bool(getattr(u, "email", None))
        if email_enabled and has_email and allow_email:
            # collect for email send but do not create DB Notification row
            recipients_map[u.email] = u.id
        else:
            # fallback: persist in-app notification
            db.session.add(
                Notification(
                    user_id=u.id,
                    request_id=request_id,
                    type=ntype,
                    title=title,
                    body=body,
                    url=url,
                )
            )

    # Enforce per-user notification cap: remove oldest notifications beyond cap.
    try:
        cfg = NotificationRetention.get()
        max_per_user = cfg.max_notifications_per_user or 20
        # Cap maximum to 20 to avoid accidental large values
        if max_per_user > 20:
            max_per_user = 20
    except Exception:
        max_per_user = 20

    # For any users we added DB rows for, ensure their total stored notifications
    # do not exceed the configured cap. We perform deletions within the same
    # session so the caller's commit will persist the removals.
    try:
        for u in users:
            # only enforce for users that will have DB rows (email-disabled or no email)
            has_email = bool(getattr(u, "email", None))
            if email_enabled and has_email:
                continue
            count = Notification.query.filter_by(user_id=u.id).count()
            if count > max_per_user:
                to_remove = count - max_per_user
                old = [n.id for n in Notification.query.filter_by(user_id=u.id).order_by(Notification.created_at.asc()).limit(to_remove).all()]
                if old:
                    Notification.query.filter(Notification.id.in_(old)).delete(synchronize_session=False)
    except Exception:
        try:
            current_app.logger.exception("Failed to enforce notification cap")
        except Exception:
            pass

    # Fire-and-forget email notifications (non-blocking). Email sending is optional/config-driven
    if recipients_map:
        subject = title
        text_body = (body or "") + ("\n\n" + url if url else "")
        html_body = None
        _send_emails_async(recipients_map, subject, text_body, html=html_body, request_id=request_id)

    # ✅ do NOT commit here; commit happens in the route after all writes


def send_request_form_autoresponder(sender_email: str) -> bool:
    """Send the configured autoresponder to `sender_email` if feature enabled.

    Returns True if an attempt was made (or successfully logged), False otherwise.
    """
    try:
        cfg = SpecialEmailConfig.get()
    except Exception:
        return False

    if not cfg or not cfg.enabled:
        return False

    # Build a subject-line friendly template listing form fields
    fields = [
        "title=<TITLE>",
        "request_type=part_number|instructions|both",
        "donor_part_number=<DONOR>",
        "target_part_number=<TARGET>",
        "no_donor_reason=unknown|needs_create",
        "sales_list=in_pricebook|not_in_pricebook|unknown",
        "price_book_number=<NUMBER>",
        "due_at=YYYY-mm-ddTHH:MM",
        "description=<SHORT TEXT>",
        "priority=low|medium|high",
    ]
    fields_for_subject = ";".join(fields)

    # Use configured first message, falling back to a default helper message
    if cfg.request_form_first_message and isinstance(cfg.request_form_first_message, str) and cfg.request_form_first_message.strip():
        body = cfg.request_form_first_message
    else:
        body = (
            "Thanks for contacting the request form inbox. To open a request by email, reply with a subject line formatted like:\n"
            "title=<TITLE>;<...fields as below...>"
        )

    # Replace placeholder if present
    body = body.replace("{fields_for_subject}", fields_for_subject)

    # Send the autoresponder (non-blocking)
    recipients_map = {sender_email: None}
    subject = "Request form: instructions to submit via subject"
    _send_emails_async(recipients_map, subject, body)
    return True


def send_request_form_validation_rejection(sender_email: str, invalid_fields: list[str]) -> bool:
    """Send automated rejection email listing invalid fields for inbound request submissions."""
    if not sender_email or not invalid_fields:
        return False

    normalized = []
    for field in invalid_fields:
        name = (field or '').strip()
        if name and name not in normalized:
            normalized.append(name)
    if not normalized:
        return False

    bullet_list = "\n".join([f"- {f}" for f in normalized])
    body = (
        "Your request-by-email submission was rejected because one or more fields failed verification.\n\n"
        "Invalid field(s):\n"
        f"{bullet_list}\n\n"
        "Please correct these fields and resend your email."
    )
    recipients_map = {sender_email: None}
    subject = "Request rejected: invalid field values"
    _send_emails_async(recipients_map, subject, body)
    return True


def send_request_form_inventory_out_of_stock_notice(sender_email: str, out_of_stock_fields: list[str], message: Optional[str] = None) -> bool:
    """Notify requester when verified inventory fields resolve as out of stock."""
    if not sender_email or not out_of_stock_fields:
        return False

    normalized = []
    for field in out_of_stock_fields:
        name = (field or '').strip()
        if name and name not in normalized:
            normalized.append(name)
    if not normalized:
        return False

    bullet_list = "\n".join([f"- {f}" for f in normalized])
    if message and isinstance(message, str) and message.strip():
        body = message.replace("{out_of_stock_fields}", bullet_list)
    else:
        body = (
            "Your request-by-email submission includes inventory fields that are currently out of stock.\n\n"
            "Out-of-stock field(s):\n"
            f"{bullet_list}\n\n"
            "You can continue by updating the parts/values, or wait for inventory restock."
        )
    recipients_map = {sender_email: None}
    subject = "Inventory notice: out-of-stock field values"
    _send_emails_async(recipients_map, subject, body)
    return True