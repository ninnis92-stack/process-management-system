from flask import Blueprint, jsonify, redirect, url_for, request, current_app
from flask_login import login_required, current_user
from ..extensions import db
from ..models import Notification
from ..models import NotificationRetention
from ..models import FeatureFlags
from sqlalchemy import or_
from datetime import datetime, timedelta

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


def _notifications_enabled() -> bool:
    try:
        return bool(getattr(FeatureFlags.get(), "enable_notifications", True))
    except Exception:
        return True


@notifications_bp.get("/unread_count")
def unread_count():
    # Return a safe default for anonymous users (avoid login redirect HTML)
    try:
        if not getattr(current_user, "is_authenticated", False):
            return jsonify({"count": 0})
    except Exception:
        current_app.logger.exception("unread_count: error checking current_user")
        return jsonify({"count": 0})

    if not _notifications_enabled():
        return jsonify({"count": 0})

    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({"count": count})


@notifications_bp.get("/latest")
def latest():
    if not _notifications_enabled():
        return jsonify([])

    # Only return notifications that are unread, or were read today.
    # Notifications marked read before start of today will no longer appear
    # in the dropdown.
    now = datetime.utcnow()
    # Determine retention cutoff based on admin settings.
    cfg = NotificationRetention.get()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if cfg and not cfg.retain_until_eod and cfg.clear_after_read_seconds is not None:
        cutoff = now - timedelta(seconds=int(cfg.clear_after_read_seconds))
    else:
        cutoff = start_of_today

    per_user_limit = getattr(cfg, "max_notifications_per_user", 20) or 20
    if per_user_limit > 20:
        per_user_limit = 20

    try:
        if not getattr(current_user, "is_authenticated", False):
            return jsonify([])
    except Exception:
        current_app.logger.exception("latest: error checking current_user")
        return jsonify([])

    try:
        items = (
            Notification.query.filter(Notification.user_id == current_user.id)
            .filter(or_(Notification.is_read == False, Notification.read_at >= cutoff))
            .order_by(Notification.created_at.desc())
            .limit(per_user_limit)
            .all()
        )
        return jsonify(
            [
                {
                    "id": n.id,
                    "title": n.title,
                    "body": n.body,
                    "url": n.url,
                    "is_read": n.is_read,
                    "created_at": n.created_at.isoformat(),
                }
                for n in items
            ]
        )
    except Exception:
        current_app.logger.exception(
            "latest: failed to fetch notifications for user %s",
            getattr(current_user, "id", None),
        )
        return jsonify([])


@notifications_bp.post("/<int:notif_id>/read")
@login_required
def mark_read(notif_id: int):
    if not _notifications_enabled():
        return jsonify({"ok": True, "disabled": True})

    n = Notification.query.filter_by(
        id=notif_id, user_id=current_user.id
    ).first_or_404()
    cfg = NotificationRetention.get()
    now = datetime.utcnow()
    # If admin configured immediate clear on check, remove the row instead
    if (
        cfg
        and cfg.clear_after_read_seconds is not None
        and int(cfg.clear_after_read_seconds) == 0
    ):
        db.session.delete(n)
    else:
        n.is_read = True
        n.read_at = now
    db.session.commit()
    return jsonify({"ok": True})


@notifications_bp.post("/mark_all_read")
@login_required
def mark_all_read():
    if not _notifications_enabled():
        return jsonify({"ok": True, "disabled": True})

    # Mark all unread notifications for current user as read
    cfg = NotificationRetention.get()
    now = datetime.utcnow()
    if (
        cfg
        and cfg.clear_after_read_seconds is not None
        and int(cfg.clear_after_read_seconds) == 0
    ):
        # delete all unread notifications
        Notification.query.filter_by(user_id=current_user.id, is_read=False).delete(
            synchronize_session=False
        )
    else:
        Notification.query.filter_by(user_id=current_user.id, is_read=False).update(
            {"is_read": True, "read_at": now}
        )
    db.session.commit()
    return jsonify({"ok": True})
