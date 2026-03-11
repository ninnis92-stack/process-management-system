"""Background task implementations for worker queues.

Tasks in this module are simple, synchronous functions intended to be
enqueued by a worker (RQ) or called directly in development. Keep tasks
small and robust to exceptions since they run outside of request
contexts.
"""

from .extensions import db
from .models import Notification, NotificationRetention
from .services.emailer import EmailService


def send_emails_task(recipients_map, subject, body, html=None, request_id=None):
    """Send emails and persist any delivery/skipped failures as Notifications.

    Parameters:
    - recipients_map: dict of email -> user_id
    - subject/body/html: message content
    - request_id: optional request id to associate notifications with
    """
    svc = EmailService()
    skipped = []
    error = None

    if recipients_map and any(isinstance(v, dict) for v in recipients_map.values()):
        for email, payload in recipients_map.items():
            res = svc.send_email(
                [email],
                (payload or {}).get("subject") or subject,
                (payload or {}).get("body") or body,
                html=(payload or {}).get("html") if isinstance(payload, dict) else html,
            )
            skipped.extend(res.get("skipped") or [])
            if res.get("error"):
                error = res.get("error")
    else:
        res = svc.send_email(list(recipients_map.keys()), subject, body, html=html)
        skipped = res.get("skipped") or []
        error = res.get("error")

    for e in skipped:
        uid = recipients_map.get(e)
        if uid:
            db.session.add(
                Notification(
                    user_id=uid,
                    request_id=request_id,
                    type="email_skipped",
                    title="Email skipped (test account)",
                    body=f"Email to {e} skipped because it is in the test domains.",
                    url=None,
                )
            )

    if error:
        for e, uid in recipients_map.items():
            if uid:
                db.session.add(
                    Notification(
                        user_id=uid,
                        request_id=request_id,
                        type="email_failed",
                        title="Email delivery failed",
                        body=f"Email delivery to {e} failed: {error}",
                        url=None,
                    )
                )

    if skipped or error:
        try:
            db.session.commit()
        except Exception:
            try:
                import logging

                logging.getLogger(__name__).exception(
                    "Failed to commit email-send notifications"
                )
            except Exception:
                pass


def fanout_notifications_task(notification_entries, request_id=None):
    if not notification_entries:
        return {"count": 0}

    try:
        svc = EmailService()
        email_enabled = bool(getattr(svc, "enabled", False))
    except Exception:
        email_enabled = False

    recipients_map = {}
    persisted_user_ids = []
    for entry in notification_entries:
        user_id = entry.get("user_id")
        email = entry.get("email")
        allow_email = bool(entry.get("allow_email", True))
        if email_enabled and email and allow_email:
            recipients_map[email] = {
                "user_id": user_id,
                "subject": entry.get("title"),
                "body": entry.get("body"),
                "html": None,
            }
            continue
        if user_id:
            db.session.add(
                Notification(
                    user_id=user_id,
                    request_id=request_id,
                    type=entry.get("type") or "generic",
                    title=entry.get("title"),
                    body=entry.get("body"),
                    url=entry.get("url"),
                )
            )
            persisted_user_ids.append(user_id)

    if persisted_user_ids:
        try:
            cfg = NotificationRetention.get()
            max_per_user = min(
                int(getattr(cfg, "max_notifications_per_user", 20) or 20), 20
            )
        except Exception:
            max_per_user = 20
        for user_id in set(persisted_user_ids):
            count = Notification.query.filter_by(user_id=user_id).count()
            if count > max_per_user:
                to_remove = count - max_per_user
                old = [
                    n.id
                    for n in Notification.query.filter_by(user_id=user_id)
                    .order_by(Notification.created_at.asc())
                    .limit(to_remove)
                    .all()
                ]
                if old:
                    Notification.query.filter(Notification.id.in_(old)).delete(
                        synchronize_session=False
                    )

    db.session.commit()

    if recipients_map:
        send_emails_task(recipients_map, None, None, request_id=request_id)
    return {
        "count": len(notification_entries),
        "emailed": len(recipients_map),
        "persisted": len(persisted_user_ids),
    }
