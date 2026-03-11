from flask import flash, redirect, render_template, url_for
from flask import request as flask_request
from flask_login import login_required

from ..extensions import db
from ..models import FeatureFlags, NotificationRetention
from .forms import NotificationRetentionForm
from .routes import admin_bp
from .utils import _is_admin_user


@admin_bp.route("/toggle_notifications", methods=["POST"])
@login_required
def toggle_notifications():
    """Flip the global notifications flag and return to dashboard."""
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    flags = FeatureFlags.get()
    flags.enable_notifications = not bool(flags.enable_notifications)
    db.session.commit()
    flash(
        f"Notifications {'enabled' if flags.enable_notifications else 'disabled'}.",
        "success",
    )
    return redirect(url_for("admin.index"))


@admin_bp.route("/notifications_retention", methods=["GET", "POST"])
@login_required
def notifications_retention():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    cfg = NotificationRetention.get()
    form = NotificationRetentionForm()
    if flask_request.method == "GET":
        form.retain_until_eod.data = bool(getattr(cfg, "retain_until_eod", True))
        if cfg and cfg.clear_after_read_seconds is not None:
            secs = int(cfg.clear_after_read_seconds)
            if secs == 0:
                form.clear_after_choice.data = "immediate"
            elif secs == 300:
                form.clear_after_choice.data = "5m"
            elif secs == 1800:
                form.clear_after_choice.data = "30m"
            elif secs == 3600:
                form.clear_after_choice.data = "1h"
            elif secs == 86400:
                form.clear_after_choice.data = "24h"
            else:
                days = max(1, min(7, int(secs / 86400)))
                form.clear_after_choice.data = "custom"
                form.custom_days.data = days
        else:
            form.clear_after_choice.data = "eod"
        form.max_notifications_per_user.data = int(
            getattr(cfg, "max_notifications_per_user", 20) or 20
        )

    if form.validate_on_submit():
        if not cfg:
            cfg = NotificationRetention()
            db.session.add(cfg)

        cfg.retain_until_eod = bool(form.retain_until_eod.data)
        choice = form.clear_after_choice.data
        if choice == "eod":
            cfg.clear_after_read_seconds = None
        elif choice == "immediate":
            cfg.clear_after_read_seconds = 0
        elif choice == "5m":
            cfg.clear_after_read_seconds = 300
        elif choice == "30m":
            cfg.clear_after_read_seconds = 1800
        elif choice == "1h":
            cfg.clear_after_read_seconds = 3600
        elif choice == "24h":
            cfg.clear_after_read_seconds = 86400
        elif choice == "custom":
            days = int(form.custom_days.data or 1)
            days = max(1, min(7, days))
            cfg.clear_after_read_seconds = days * 86400
            cfg.retain_until_eod = False

        maxn = int(form.max_notifications_per_user.data or 20)
        cfg.max_notifications_per_user = max(1, min(20, maxn))
        cfg.max_retention_days = 7

        db.session.commit()
        flash("Notification retention updated.", "success")
        return redirect(url_for("admin.notifications_retention"))

    return render_template("admin_notifications_retention.html", form=form, cfg=cfg)
