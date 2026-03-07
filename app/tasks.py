"""Background task implementations for worker queues.

Tasks in this module are simple, synchronous functions intended to be
enqueued by a worker (RQ) or called directly in development. Keep tasks
small and robust to exceptions since they run outside of request
contexts.
"""

from .services.emailer import EmailService
from .extensions import db
from .models import Notification


def send_emails_task(recipients_map, subject, body, html=None, request_id=None):
    """Send emails and persist any delivery/skipped failures as Notifications.

    Parameters:
    - recipients_map: dict of email -> user_id
    - subject/body/html: message content
    - request_id: optional request id to associate notifications with
    """
    svc = EmailService()
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
