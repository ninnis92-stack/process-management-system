from datetime import datetime, timedelta
from flask import url_for
from ..extensions import db
from ..models import Request as ReqModel, User, Notification
from ..models import SpecialEmailConfig
from ..models import FeatureFlags
from .. import notifcations as notifications_module


def users_in_dept(dept: str):
    return User.query.filter_by(department=dept, is_active=True).all()


def send_due_soon_notifications(app, hours=24, commit: bool = False):
    now = datetime.utcnow()
    soon = now + timedelta(hours=hours)

    # not closed + has due date within window
    reqs = (
        ReqModel.query.filter(ReqModel.due_at != None)
        .filter(ReqModel.due_at <= soon)
        .filter(ReqModel.status != "CLOSED")
        .all()
    )

    for req in reqs:
        link = url_for("requests.request_detail", request_id=req.id, _external=False)

        targets = users_in_dept(req.owner_department)
        if req.created_by_user_id:
            creator = db.session.get(User, req.created_by_user_id)
            if creator and creator.is_active:
                targets.append(creator)

        # dedupe per user per req per window
        dedupe = f"due_{hours}h:req_{req.id}"

        for u in {t.id: t for t in targets}.values():
            exists = Notification.query.filter_by(
                user_id=u.id, dedupe_key=dedupe
            ).first()
            if exists:
                continue

            db.session.add(
                Notification(
                    user_id=u.id,
                    request_id=req.id,
                    type="due_soon",
                    title=f"Due soon: Request #{req.id}",
                    body=f"Due at {req.due_at}",
                    url=link,
                    dedupe_key=dedupe,
                )
            )

    if commit:
        db.session.commit()


def send_high_priority_nudges(app, commit: bool = False):
    """Send nudges for high-priority open requests according to admin config.

    This function will create an in-app `Notification` for the responsible
    user (assigned user if present, otherwise department users) and also
    fire an email for the same recipient. Nudges are rate-limited per-user
    per-request based on `SpecialEmailConfig.nudge_interval_hours`.
    """
    try:
        cfg = SpecialEmailConfig.get()
    except Exception:
        return

    # Respect both the special-email config and global feature flags
    flags = None
    try:
        flags = FeatureFlags.get()
    except Exception:
        flags = None

    if not cfg or not cfg.nudge_enabled:
        return
    if flags and not getattr(flags, "enable_nudges", True):
        return

    interval = int(cfg.nudge_interval_hours or 24)
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=interval)
    # Respect administrative minimum delay: do not nudge requests created
    # within `nudge_min_delay_hours` of their creation. Default is 4 hours.
    try:
        raw_min_delay = getattr(cfg, "nudge_min_delay_hours", None)
        min_delay = 4 if raw_min_delay is None else int(raw_min_delay)
    except Exception:
        min_delay = 4

    # Find high-priority requests still open
    reqs = (
        ReqModel.query.filter(ReqModel.priority == "high")
        .filter(ReqModel.status != "CLOSED")
        .all()
    )
    for req in reqs:
        # determine targets: prefer explicit assignee
        targets = []
        if req.assigned_to_user_id:
            u = db.session.get(User, req.assigned_to_user_id)
            if u and u.is_active:
                targets.append(u)
        else:
            # fallback: all active users in owner department
            targets = User.query.filter_by(
                department=req.owner_department, is_active=True
            ).all()

        link = url_for("requests.request_detail", request_id=req.id, _external=False)

        for u in {t.id: t for t in targets}.values():
            # skip if we've sent a nudge within the interval
            recent = (
                Notification.query.filter_by(
                    user_id=u.id, dedupe_key=f"nudge:req_{req.id}"
                )
                .filter(Notification.created_at >= cutoff)
                .first()
            )
            if recent:
                continue

            # skip if request is too new (within admin-configured delay)
            try:
                if req.created_at:
                    age_seconds = (now - req.created_at).total_seconds()
                    # only enforce the min-delay for positive ages; if created_at
                    # is unexpectedly in the future, allow the nudge path.
                    if age_seconds >= 0 and age_seconds < (min_delay * 3600):
                        continue
            except Exception:
                # on any problem reading created_at, be conservative and skip
                continue

            # create in-app notification
            db.session.add(
                Notification(
                    user_id=u.id,
                    request_id=req.id,
                    type="nudge",
                    title=f"Reminder: High priority request #{req.id}",
                    body=f"Request '{req.title}' is still open.",
                    url=link,
                    dedupe_key=f"nudge:req_{req.id}",
                )
            )

            # send email in background (non-blocking)
            if getattr(u, "email", None):
                recipients_map = {u.email: u.id}
                subject = f"Reminder: Request #{req.id} still open"
                text_body = f"Your attention is requested: request #{req.id} ({req.title}) remains open.\n\n{link}"
                try:
                    notifications_module._send_emails_async(
                        recipients_map, subject, text_body, html=None, request_id=req.id
                    )
                except Exception:
                    # best-effort; do not abort nudge loop
                    try:
                        app.logger.exception("Failed to queue nudge email")
                    except Exception:
                        pass

    if commit:
        try:
            db.session.commit()
        except Exception:
            try:
                app.logger.exception("Failed to commit nudge notifications")
            except Exception:
                pass
    else:
        # Ensure newly-added Notification objects are flushed to the DB so
        # subsequent queries in the same test/request context can observe
        # them without requiring a full commit. Flushing is safe here as it
        # does not finalize the transaction.
        try:
            db.session.flush()
        except Exception:
            try:
                app.logger.exception("Failed to flush nudge notifications")
            except Exception:
                pass
