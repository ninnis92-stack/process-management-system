"""In-app noti***REMOVED***cation utilities and email delivery helpers.

This module persists `Noti***REMOVED***cation` rows in the DB and attempts to send
emails to users. In development the code falls back to a thread-based
background sender; when `RQ_ENABLED` and `REDIS_URL` are con***REMOVED***gured the
send will be enqueued to RQ so a separate worker can process deliveries.

Keep the send path idempotent and non-blocking from request handlers.
"""

from .extensions import db
from .models import Noti***REMOVED***cation, User
from flask import current_app
from threading import Thread

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
    return User.query.***REMOVED***lter_by(department=dept, is_active=True).all()


def _send_emails_async(recipients_map, subject, body, html=None, request_id=None):
    """Send emails in background.

    recipients_map: dict mapping email -> user_id (or None)
    """
    from flask import current_app as _current
    try:
        app = _current._get_current_object()
    except Exception:
        app = None

    # If RQ (Redis Queue) is enabled and con***REMOVED***gured, enqueue the send task.
    rq_enabled = False
    redis_url = None
    if app:
        rq_enabled = bool(app.con***REMOVED***g.get("RQ_ENABLED", False))
        redis_url = app.con***REMOVED***g.get("REDIS_URL") or app.con***REMOVED***g.get("RQ_REDIS_URL")

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
                        db.session.add(Noti***REMOVED***cation(
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
                            db.session.add(Noti***REMOVED***cation(
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
                        _current.logger.exception("Failed to commit email-send noti***REMOVED***cations")

            except Exception:
                _current.logger.exception("Email sending failed")

    Thread(target=_send, daemon=True).start()


def notify_users(users, title, body=None, url=None, ntype="generic", request_id=None):
    # Persist in-app noti***REMOVED***cations
    recipients_map = {}
    for u in users:
        db.session.add(
            Noti***REMOVED***cation(
                user_id=u.id,
                request_id=request_id,
                type=ntype,
                title=title,
                body=body,
                url=url,
            )
        )
        if getattr(u, "email", None):
            recipients_map[u.email] = u.id

    # Fire-and-forget email noti***REMOVED***cations (non-blocking). Email sending is optional/con***REMOVED***g-driven
    if recipients_map:
        subject = title
        text_body = (body or "") + ("\n\n" + url if url else "")
        html_body = None
        _send_emails_async(recipients_map, subject, text_body, html=html_body, request_id=request_id)

    # ✅ do NOT commit here; commit happens in the route after all writes