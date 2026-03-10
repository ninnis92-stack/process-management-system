"""In-app notification utilities and email delivery helpers.

This module persists `Notification` rows in the DB and attempts to send
emails to users. In development the code falls back to a thread-based
background sender; when `RQ_ENABLED` and `REDIS_URL` are configured the
send will be enqueued to RQ so a separate worker can process deliveries.

Keep the send path idempotent and non-blocking from request handlers.
"""

from .extensions import db
from .models import FeatureFlags, Notification, User, UserDepartment, SpecialEmailConfig, NotificationRetention
from .models import DepartmentFormAssignment, FormTemplate
from flask import current_app
from threading import Thread
from typing import Optional

from .services.emailer import EmailService
from .services.job_dispatcher import run_job
import importlib
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import sessionmaker

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
    fanout_notifications_task = getattr(_tasks_mod, "fanout_notifications_task", None)
except (
    Exception
):  # pragma: no cover - tasks module may be unavailable to static checker
    send_emails_task = None
    fanout_notifications_task = None


def _send_notification_fanout_async(notification_entries, request_id=None):
    from flask import current_app as _current

    try:
        app = _current._get_current_object()
    except Exception:
        app = None

    if app and (getattr(app, "testing", False) or app.config.get("TESTING")):
        if fanout_notifications_task:
            fanout_notifications_task(notification_entries, request_id=request_id)
        return

    rq_enabled = bool(app.config.get("RQ_ENABLED", False)) if app else False
    redis_url = (app.config.get("REDIS_URL") or app.config.get("RQ_REDIS_URL")) if app else None

    if rq_enabled and redis_url and fanout_notifications_task:
        try:
            conn = Redis.from_url(redis_url)
            q = Queue("notifications", connection=conn)
            q.enqueue(fanout_notifications_task, notification_entries, request_id)
            return
        except Exception:
            try:
                _current.logger.exception("Failed to enqueue notification fan-out job; falling back to thread")
            except Exception:
                pass

    def _send():
        if app is None or not fanout_notifications_task:
            return
        with app.app_context():
            try:
                run_job(
                    "fanout_notifications",
                    fanout_notifications_task,
                    notification_entries,
                    request_id=request_id,
                    queue_name="notifications",
                    payload={"recipient_count": len(notification_entries or []), "request_id": request_id},
                )
            except Exception:
                _current.logger.exception("Notification fan-out failed")

    Thread(target=_send, daemon=True).start()


def _get_latest_department_template(department_code: str):
    """Return the latest assigned form template for a department.

    The autoresponder uses this so generated key/value instructions match the
    current admin-configured department form.
    """
    assigned = (
        DepartmentFormAssignment.query.filter_by(department_name=department_code)
        .order_by(DepartmentFormAssignment.created_at.desc())
        .first()
    )
    return db.session.get(FormTemplate, assigned.template_id) if assigned else None


def users_in_department(dept: str):
    normalized = (dept or "").strip().upper()
    if not normalized:
        return []
    assignment_candidates = (
        User.query.options(joinedload(User.departments))
        .outerjoin(
            UserDepartment,
            and_(UserDepartment.user_id == User.id, UserDepartment.department == normalized),
        )
        .filter(User.is_active.is_(True))
        .filter(
            or_(
                User.department == normalized,
                UserDepartment.id.isnot(None),
            )
        )
        .order_by(User.email.asc())
        .all()
    )
    routed_candidates = (
        User.query.options(joinedload(User.departments))
        .filter(User.is_active.is_(True))
        .filter(User.notification_departments_json.like(f'%"{normalized}"%'))
        .order_by(User.email.asc())
        .all()
    )
    watched_candidates = (
        User.query.options(joinedload(User.departments))
        .filter(User.is_active.is_(True))
        .filter(User.is_admin.is_(True))
        .filter(User.watched_departments_json.like(f'%"{normalized}"%'))
        .order_by(User.email.asc())
        .all()
    )
    candidates = list(assignment_candidates) + list(routed_candidates) + list(watched_candidates)
    recipients = []
    seen = set()
    for user in candidates:
        watched_match = normalized in (getattr(user, "watched_departments", []) or [])
        primary_match = (getattr(user, "department", "") or "").strip().upper() == normalized
        routed_match = normalized in (getattr(user, "notification_departments", []) or [])
        assignment_match = any(
            (getattr(assignment, "department", "") or "").strip().upper() == normalized
            and getattr(assignment, "is_active_assignment", True)
            for assignment in (getattr(user, "departments", []) or [])
        )

        # Admins can monitor a subset of departments from their user settings.
        # When that list is configured, queue/broadcast notifications should
        # follow the monitored departments instead of every department the admin
        # could technically access; direct notifications still use explicit
        # recipient lists elsewhere.
        if getattr(user, "is_admin", False):
            monitored_departments = list(getattr(user, "watched_departments", []) or [])
            if monitored_departments:
                if not (watched_match or routed_match):
                    continue
            elif not (primary_match or routed_match or assignment_match):
                continue
        elif not (primary_match or routed_match or assignment_match):
            continue
        if getattr(user, "id", None) in seen:
            continue
        seen.add(user.id)
        recipients.append(user)
    return recipients


def _notification_recipients(users, title, body=None):
    recipients = []
    seen = set()
    for user in users or []:
        if not user or not getattr(user, "id", None) or not getattr(user, "is_active", True):
            continue
        if user.id not in seen:
            recipients.append(
                {
                    "user": user,
                    "subject": title,
                    "body": body,
                    "is_backup": False,
                    "source_user": user,
                }
            )
            seen.add(user.id)

    for entry in list(recipients):
        user = entry["user"]
        backup = getattr(user, "backup_approver", None)
        if not backup or not getattr(backup, "id", None):
            continue
        if not getattr(backup, "is_active", True) or backup.id == user.id or backup.id in seen:
            continue
        source_label = getattr(user, "name", None) or getattr(user, "email", None) or "this teammate"
        prefix = f"You received this as backup approver for {source_label}."
        backup_body = prefix if not body else f"{prefix}\n\n{body}"
        recipients.append(
            {
                "user": backup,
                "subject": f"{title} — backup coverage",
                "body": backup_body,
                "is_backup": True,
                "source_user": user,
            }
        )
        seen.add(backup.id)

    return recipients


def _send_emails_async(recipients_map, subject=None, body=None, html=None, request_id=None):
    """Send emails in background.

    recipients_map: dict mapping email -> user_id (legacy) or payload dict
    """
    if recipients_map and all(not isinstance(v, dict) for v in recipients_map.values()):
        recipients_map = {
            email: {
                "user_id": user_id,
                "subject": subject,
                "body": body,
                "html": html,
            }
            for email, user_id in recipients_map.items()
        }

    from flask import current_app as _current

    try:
        app = _current._get_current_object()
    except Exception:
        app = None

    # Tests generally validate notification side effects, not actual email
    # dispatch. Avoid spawning background threads against an in-memory SQLite
    # database because concurrent commits can invalidate active cursors and make
    # otherwise-correct tests flaky.
    if app and (getattr(app, "testing", False) or app.config.get("TESTING")):
        return

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
                _current.logger.exception(
                    "Failed to enqueue email send job; falling back to thread"
                )
            except Exception:
                pass

    # Fallback: run in a background thread using captured app context (dev-safe)
    def _send():
        if app is None:
            try:
                _current.logger.warning(
                    "Email send skipped: no app context available for background thread"
                )
            except Exception:
                pass
            return

        with app.app_context():
            def _deliver_email_job():
                svc = EmailService()
                skipped = []
                error = None

                for email, payload in recipients_map.items():
                    res = svc.send_email(
                        [email],
                        payload.get("subject") or subject,
                        payload.get("body") or body,
                        html=payload.get("html") if isinstance(payload, dict) else html,
                    )
                    skipped.extend(res.get("skipped") or [])
                    if res.get("error"):
                        error = res.get("error")

                # Persist notification rows about skipped or failed deliveries
                # using a fresh SQLAlchemy session to avoid interfering with the
                # main thread's session/transaction state. Committing from the
                # background thread on the shared `db.session` can reset active
                # cursors in the main thread and cause InterfaceError when tests
                # or callers attempt to fetch results concurrently.
                if skipped or error:
                    try:
                        Session = sessionmaker(bind=db.engine)
                        session = Session()
                        try:
                            for e in skipped:
                                payload = recipients_map.get(e) or {}
                                uid = payload.get("user_id") if isinstance(payload, dict) else payload
                                if uid:
                                    session.add(
                                        Notification(
                                            user_id=uid,
                                            request_id=request_id,
                                            type="email_skipped",
                                            title="Email skipped (test account)",
                                            body=(
                                                f"Email to {e} skipped because it is in the test domains."
                                            ),
                                            url=None,
                                        )
                                    )

                            if error:
                                for e, payload in recipients_map.items():
                                    uid = payload.get("user_id") if isinstance(payload, dict) else payload
                                    if uid:
                                        session.add(
                                            Notification(
                                                user_id=uid,
                                                request_id=request_id,
                                                type="email_failed",
                                                title="Email delivery failed",
                                                body=f"Email delivery to {e} failed: {error}",
                                                url=None,
                                            )
                                        )

                            session.commit()
                        finally:
                            try:
                                session.close()
                            except Exception:
                                pass
                    except Exception:
                        try:
                            _current.logger.exception(
                                "Failed to commit email-send notifications"
                            )
                        except Exception:
                            pass

                return {
                    "recipients": list(recipients_map.keys()),
                    "skipped": skipped,
                    "error": error,
                }

            try:
                run_job(
                    "send_emails",
                    _deliver_email_job,
                    queue_name="emails",
                    payload={
                        "request_id": request_id,
                        "recipient_count": len(recipients_map or {}),
                        "subject": subject or next(
                            (
                                payload.get("subject")
                                for payload in (recipients_map or {}).values()
                                if isinstance(payload, dict) and payload.get("subject")
                            ),
                            None,
                        ),
                    },
                )
            except Exception:
                _current.logger.exception("Email sending failed")

    Thread(target=_send, daemon=True).start()


def notify_users(
    users,
    title,
    body=None,
    url=None,
    ntype="generic",
    request_id=None,
    allow_email: bool = True,
):
    try:
        in_app_notifications_enabled = bool(
            getattr(FeatureFlags.get(), "enable_notifications", True)
        )
    except Exception:
        in_app_notifications_enabled = True

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

    recipients = _notification_recipients(users, title, body)
    notification_entries = []

    try:
        fanout_threshold = int(current_app.config.get("NOTIFICATION_FANOUT_ASYNC_THRESHOLD", 50) or 50)
    except Exception:
        fanout_threshold = 50

    for entry in recipients:
        u = entry["user"]
        resolved_title = entry["subject"]
        resolved_body = entry["body"]

        # apply optional department-specific template if configured.  Templates
        # are simple Jinja2 strings and are evaluated with the current user,
        # source_user, title and body in the context.  Errors during template
        # rendering are logged but do not interrupt notification delivery.
        templ = None
        if getattr(u, "department_obj", None):
            templ = getattr(u.department_obj, "notification_template", None)
        if templ:
            try:
                from jinja2 import Template

                rendered = Template(templ).render(
                    title=resolved_title,
                    body=resolved_body or "",
                    user=u,
                    source_user=entry.get("source_user"),
                )
                # rendered text becomes the body; subject remains unchanged
                resolved_body = rendered
            except Exception:
                current_app.logger.exception(
                    "failed to render notification template for dept %s",
                    getattr(u.department_obj, "code", None),
                )

        notification_entries.append(
            {
                "user_id": u.id,
                "email": getattr(u, "email", None),
                "title": resolved_title,
                "body": (resolved_body or "") + ("\n\n" + url if url else "") if email_enabled and getattr(u, "email", None) and allow_email else resolved_body,
                "url": url,
                "type": ntype,
                "allow_email": allow_email,
            }
        )

    if fanout_threshold > 0 and len(notification_entries) >= fanout_threshold:
        _send_notification_fanout_async(notification_entries, request_id=request_id)
        return

    for entry in notification_entries:
        has_email = bool(entry.get("email"))
        if email_enabled and has_email and entry.get("allow_email", True):
            recipients_map[entry["email"]] = {
                "user_id": entry["user_id"],
                "subject": entry["title"],
                "body": entry["body"],
                "html": None,
            }
        elif in_app_notifications_enabled:
            db.session.add(
                Notification(
                    user_id=entry["user_id"],
                    request_id=request_id,
                    type=entry["type"],
                    title=entry["title"],
                    body=entry["body"],
                    url=entry["url"],
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
        for entry in notification_entries:
            u = type("NotificationUser", (), {"id": entry["user_id"], "email": entry.get("email")})
            # only enforce for users that will have DB rows (email-disabled or no email)
            has_email = bool(getattr(u, "email", None))
            if (email_enabled and has_email and entry.get("allow_email", True)) or not in_app_notifications_enabled:
                continue
            count = Notification.query.filter_by(user_id=u.id).count()
            if count > max_per_user:
                to_remove = count - max_per_user
                old = [
                    n.id
                    for n in Notification.query.filter_by(user_id=u.id)
                    .order_by(Notification.created_at.asc())
                    .limit(to_remove)
                    .all()
                ]
                if old:
                    Notification.query.filter(Notification.id.in_(old)).delete(
                        synchronize_session=False
                    )
    except Exception:
        try:
            current_app.logger.exception("Failed to enforce notification cap")
        except Exception:
            pass

    # Fire-and-forget email notifications (non-blocking). Email sending is optional/config-driven
    if recipients_map:
        _send_emails_async(
            recipients_map,
            subject=title,
            body=(body or "") + ("\n\n" + url if url else ""),
            html=None,
            request_id=request_id,
        )

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

    # Build a subject-line friendly template listing form fields.
    # Prefer department-assigned dynamic form fields when present.
    fields = []
    try:
        dept = (getattr(cfg, "request_form_department", "A") or "A").strip().upper()
        template = _get_latest_department_template(dept)
        if template:
            template_fields = sorted(
                list(getattr(template, "fields", []) or []),
                key=lambda f: getattr(f, "created_at", getattr(f, "id", 0)),
            )
            for field in template_fields:
                field_type = (getattr(field, "field_type", "") or "").strip().lower()
                if field_type == "file":
                    continue
                name = (getattr(field, "name", "") or "").strip()
                if not name:
                    continue
                options = [
                    str(getattr(o, "value", "")).strip()
                    for o in (getattr(field, "options", []) or [])
                    if str(getattr(o, "value", "")).strip()
                ]
                if options:
                    placeholder = "|".join(options)
                elif field_type in ("date", "datetime") or name in ("due_at", "due"):
                    placeholder = "YYYY-mm-ddTHH:MM"
                else:
                    placeholder = "<VALUE>"
                fields.append(f"{name}={placeholder}")
    except Exception:
        fields = []

    # Fallback to baseline fields if no dynamic template fields are available.
    if not fields:
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
    if (
        cfg.request_form_first_message
        and isinstance(cfg.request_form_first_message, str)
        and cfg.request_form_first_message.strip()
    ):
        body = cfg.request_form_first_message
    else:
        body = (
            "Thanks for contacting the request form inbox. To open a request by email, reply with a subject line formatted like:\n"
            f"{fields_for_subject}"
        )

    # Replace placeholder if present
    body = body.replace("{fields_for_subject}", fields_for_subject)

    # Send the autoresponder (non-blocking)
    recipients_map = {sender_email: None}
    subject = "Request form: instructions to submit via subject"
    _send_emails_async(recipients_map, subject, body)
    return True


def send_request_form_validation_rejection(
    sender_email: str, invalid_fields: list[str]
) -> bool:
    """Send automated rejection email listing invalid fields for inbound request submissions."""
    if not sender_email or not invalid_fields:
        return False

    normalized = []
    for field in invalid_fields:
        name = (field or "").strip()
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


def send_request_form_inventory_out_of_stock_notice(
    sender_email: str, out_of_stock_fields: list[str], message: Optional[str] = None
) -> bool:
    """Notify requester when verified inventory fields resolve as out of stock."""
    if not sender_email or not out_of_stock_fields:
        return False

    normalized = []
    for field in out_of_stock_fields:
        name = (field or "").strip()
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
