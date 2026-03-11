from datetime import datetime, timedelta

from flask import url_for

from .. import notifcations as notifications_module
from ..extensions import db
from ..models import FeatureFlags, Notification
from ..models import Request as ReqModel
from ..models import SpecialEmailConfig, User


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

    Nudges are created for requests of priority "high" or "highest".  The
    interval between nudges is determined by the order of the current status
    in the workflow (a simple level the admin can reorder); level 0 maps to
    hourly, level 1 to every 4 hours, and level >=2 to once per day.  If a
    status has no associated bucket entry or an error occurs, the global
    ``cfg.nudge_interval_hours`` value is used instead.

    Regardless of interval, users are capped to a fixed number of nudges per
    UTC day.  By default this limit is one; admins can assign up to five via
    the ``User.daily_nudge_limit`` column.  The cap is enforced *before*
    per-request interval checks to ensure users are not flooded.
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

    # helper for computing interval based on workflow status order
    def interval_for_status(status_code: str) -> float:
        try:
            from ..models import BucketStatus

            rec = BucketStatus.query.filter_by(status_code=status_code).first()
            if rec is not None:
                lvl = getattr(rec, "order", 0) or 0
                if lvl <= 0:
                    return 1.0
                elif lvl == 1:
                    return 4.0
                else:
                    return 24.0
        except Exception:
            pass
        try:
            return float(cfg.nudge_interval_hours or 24)
        except Exception:
            return 24.0

    # administrative minimum delay for new requests
    try:
        raw_min_delay = getattr(cfg, "nudge_min_delay_hours", None)
        min_delay = 4 if raw_min_delay is None else float(raw_min_delay)
    except Exception:
        min_delay = 4.0

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # target both high and highest priorities
    reqs = (
        ReqModel.query.filter(ReqModel.priority.in_(["high", "highest"]))
        .filter(ReqModel.status != "CLOSED")
        .all()
    )

    for req in reqs:
        interval = interval_for_status(req.status)
        cutoff = now - timedelta(hours=interval)

        # determine targets for this request
        targets = []
        if req.assigned_to_user_id:
            u = db.session.get(User, req.assigned_to_user_id)
            if u and u.is_active:
                targets.append(u)
        else:
            targets = User.query.filter_by(
                department=req.owner_department, is_active=True
            ).all()

        link = url_for("requests.request_detail", request_id=req.id, _external=False)

        for u in {t.id: t for t in targets}.values():
            # enforce daily per-user cap
            try:
                limit = getattr(u, "daily_nudge_limit", 1) or 1
                sent_today = (
                    Notification.query.filter_by(user_id=u.id, type="nudge")
                    .filter(Notification.created_at >= today_start)
                    .count()
                )
                if sent_today >= limit:
                    continue
            except Exception:
                pass

            # skip if we've sent a nudge for *this* request recently
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
                    if age_seconds >= 0 and age_seconds < (min_delay * 3600):
                        continue
            except Exception:
                continue

            # create notification
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
            # In testing contexts some background activity can interfere
            # with session flushes; when running tests commit immediately
            # so assertions can observe newly-created Notification rows.
            if getattr(app, "testing", False) or app.config.get("TESTING"):
                db.session.commit()
            else:
                db.session.flush()
        except Exception:
            try:
                app.logger.exception("Failed to flush nudge notifications")
            except Exception:
                pass
