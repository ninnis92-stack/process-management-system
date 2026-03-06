from flask import Blueprint, render_template, redirect, url_for, flash, current_app, session, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import User
from .forms import AdminCreateUserForm, SiteConfigForm, DepartmentForm, SSOAssignForm
from .forms import NotificationRetentionForm
from ..models import Request as ReqModel, Artifact, Submission, SiteConfig, Department
from ..models import StatusOption, DepartmentEditor
from ..models import IntegrationConfig
from datetime import datetime, timedelta
from flask import request as flask_request
from ..models import Notification, AuditLog, NotificationRetention, StatusBucket, BucketStatus
from ..models import FeatureFlags, RejectRequestConfig
from urllib.parse import unquote

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _is_admin_user():
    # Basic admin check
    if not (current_user.is_authenticated and getattr(current_user, "is_admin", False)):
        return False

    # If SSO is enabled and admin access requires MFA, enforce it.
    if current_app.config.get("SSO_ENABLED") and current_app.config.get("SSO_REQUIRE_MFA"):
        # SSO login flow should set `session['sso_mfa'] = True` when MFA was verified.
        return bool(session.get("sso_mfa", False))

    return True


@admin_bp.route("/users")
@login_required
def list_users():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    users = User.query.order_by(User.email).all()
    return render_template("admin_users.html", users=users)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@login_required
def create_user():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = AdminCreateUserForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        name = form.name.data.strip() if form.name.data else None
        dept = form.department.data
        pw = form.password.data or "password123"
        is_active = bool(form.is_active.data)

        existing = User.query.filter_by(email=email).first()
        if existing:
            existing.name = name or existing.name
            existing.department = dept
            if form.password.data:
                existing.password_hash = generate_password_hash(pw, method="pbkdf2:sha256")
            existing.is_active = is_active
            db.session.commit()
            flash(f"Updated user {email}.", "success")
            return redirect(url_for("admin.list_users"))

        u = User(
            email=email,
            name=name,
            department=dept,
            password_hash=generate_password_hash(pw, method="pbkdf2:sha256"),
            is_active=is_active,
        )
        db.session.add(u)
        db.session.commit()
        flash(f"Created user {email}.", "success")
        return redirect(url_for("admin.list_users"))

    return render_template("admin_new_user.html", form=form)


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit_user(user_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    u = User.query.get_or_404(user_id)
    form = AdminCreateUserForm(obj=u)
    # don't prefill password
    form.password.data = None

    if form.validate_on_submit():
        u.email = form.email.data.strip().lower()
        u.name = form.name.data.strip() if form.name.data else None
        u.department = form.department.data
        if form.password.data:
            u.password_hash = generate_password_hash(form.password.data, method="pbkdf2:sha256")
        u.is_active = bool(form.is_active.data)
        # Keep existing is_admin unless explicitly changed elsewhere
        db.session.commit()
        flash(f"Updated user {u.email}.", "success")
        return redirect(url_for("admin.list_users"))

    return render_template("admin_new_user.html", form=form, edit=u)


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    if current_user.id == user_id:
        flash("You cannot delete your own account.", "warning")
        return redirect(url_for("admin.list_users"))

    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    flash(f"Deleted user {u.email}.", "success")
    return redirect(url_for("admin.list_users"))



@admin_bp.route('/users/<int:user_id>/impersonate', methods=['POST'])
@login_required


def impersonate_user(user_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    if current_user.id == user_id:
        flash('Cannot impersonate yourself.', 'warning')
        return redirect(url_for('admin.list_users'))

    target = User.query.get_or_404(user_id)
    if not target.is_active:
        flash('Cannot impersonate an inactive user.', 'warning')
        return redirect(url_for('admin.list_users'))
    # record admin id and the department to impersonate
    session['impersonate_admin_id'] = current_user.id
    session['impersonate_dept'] = target.department
    session['impersonate_started_at'] = datetime.utcnow().isoformat()

    # add an audit entry (system-level; request_id left null)
    entry = AuditLog(
        request_id=None,
        actor_type='user',
        actor_user_id=current_user.id,
        actor_label=current_user.email,
        action_type='impersonation_start',
        note=f"Started impersonation as department {target.department}",
        event_ts=datetime.utcnow(),
    )
    db.session.add(entry)
    db.session.commit()

    flash(f'Now acting as a member of Dept {target.department} (you remain {current_user.email}).', 'info')
    return redirect(url_for('requests.dashboard'))



@admin_bp.route('/impersonate/dept', methods=['POST'])
@login_required
def impersonate_dept():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    dept = flask_request.form.get('dept') or flask_request.args.get('dept')
    if not dept or dept.upper() not in ('A', 'B', 'C'):
        flash('Invalid department selected.', 'warning')
        return redirect(url_for('admin.list_users'))
    dept = dept.upper()

    session['impersonate_admin_id'] = current_user.id
    session['impersonate_dept'] = dept
    session['impersonate_started_at'] = datetime.utcnow().isoformat()

    entry = AuditLog(
        request_id=None,
        actor_type='user',
        actor_user_id=current_user.id,
        actor_label=current_user.email,
        action_type='impersonation_start',
        note=f"Started impersonation as department {dept}",
    )
    db.session.add(entry)
    db.session.commit()

    flash(f'Now acting as a member of Dept {dept} (you remain {current_user.email}).', 'info')
    return redirect(url_for('requests.dashboard'))


@admin_bp.route('/impersonate/stop', methods=['POST'])
@login_required
def stop_impersonation():
    admin_id = session.get('impersonate_admin_id')
    if not admin_id:
        flash('Not currently impersonating.', 'warning')
        return redirect(url_for('requests.dashboard'))

    # record stop audit
    entry = AuditLog(
        request_id=None,
        actor_type='user',
        actor_user_id=current_user.id,
        actor_label=current_user.email,
        action_type='impersonation_stop',
        note=f"Stopped impersonation; admin {current_user.email} restored their session",
        event_ts=datetime.utcnow(),
    )
    db.session.add(entry)
    db.session.commit()

    # clear impersonation flags
    session.pop('impersonate_admin_id', None)
    session.pop('impersonate_dept', None)
    session.pop('impersonate_started_at', None)
    flash('Stopped acting-as; returned to your normal admin session.', 'success')
    return redirect(url_for('admin.list_users'))



@admin_bp.route("/monitor")
@login_required
def monitor():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    dept = (flask_request.args.get("dept") or "B").upper()
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=24)

    # Gather admin-only metrics
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    admin_count = User.query.filter_by(is_admin=True).count()
    recent_email_issues = Notification.query.filter(Notification.type.in_(["email_failed", "email_skipped"]))\
        .order_by(Notification.created_at.desc()).limit(20).all()

    if dept == "A":
        # Show requests created by users in Dept A (monitoring view)
        reqs = ReqModel.query.join(User, ReqModel.created_by_user_id == User.id).filter(
            User.department == "A"
        ).order_by(ReqModel.updated_at.desc()).all()
        dashboard_html = render_template("dashboard.html", mode="A", requests=reqs, now=now)
        return render_template("admin_monitor.html", dept=dept, dashboard_html=dashboard_html,
                               total_users=total_users, active_users=active_users, admin_count=admin_count,
                               recent_email_issues=recent_email_issues)

    if dept == "B":
        # Build buckets similar to Dept B dashboard but for monitoring
        buckets = {
            "New from A": ReqModel.query.filter(
                ReqModel.owner_department == "B",
                ReqModel.status == "NEW_FROM_A",
            ).order_by(ReqModel.updated_at.desc()).all(),
            "In progress by Department B": ReqModel.query.filter(
                ReqModel.owner_department == "B",
                ReqModel.status == "B_IN_PROGRESS",
            ).order_by(ReqModel.updated_at.desc()).all(),
            "Pending review from Department A": ReqModel.query.filter(
                ReqModel.owner_department == "B",
                ReqModel.status == "WAITING_ON_A_RESPONSE",
            ).order_by(ReqModel.updated_at.desc()).all(),
            "Needs changes": ReqModel.query.filter(
                ReqModel.owner_department == "B",
                ReqModel.status == "C_NEEDS_CHANGES",
            ).order_by(ReqModel.updated_at.desc()).all(),
            "Exec approval required": ReqModel.query.filter(
                ReqModel.owner_department == "B",
                ReqModel.status == "EXEC_APPROVAL",
            ).order_by(ReqModel.updated_at.desc()).all(),
            "Approved by C": ReqModel.query.filter(
                ReqModel.owner_department == "B",
                ReqModel.status == "C_APPROVED",
            ).order_by(ReqModel.updated_at.desc()).all(),
            "Final review": ReqModel.query.filter(
                ReqModel.owner_department == "B",
                ReqModel.status == "B_FINAL_REVIEW",
            ).order_by(ReqModel.updated_at.desc()).all(),
            "Sent to A": ReqModel.query.filter(
                ReqModel.owner_department == "B",
                ReqModel.status == "SENT_TO_A",
            ).order_by(ReqModel.updated_at.desc()).all(),
            "Under review by Department C": ReqModel.query.filter(
                ReqModel.owner_department == "B",
                ReqModel.status == "PENDING_C_REVIEW",
            ).order_by(ReqModel.updated_at.desc()).all(),
            "Closed": ReqModel.query.filter(
                ReqModel.owner_department == "B",
                ReqModel.status == "CLOSED",
            ).order_by(ReqModel.updated_at.desc()).all(),
            "All (B)": ReqModel.query.filter(
                ReqModel.owner_department == "B",
            ).order_by(ReqModel.updated_at.desc()).all(),
        }

        # status counts for quick badges
        status_counts = {code: ReqModel.query.filter(ReqModel.owner_department == "B", ReqModel.status == code).count() for code in [
            "B_IN_PROGRESS", "WAITING_ON_A_RESPONSE", "PENDING_C_REVIEW", "EXEC_APPROVAL", "B_FINAL_REVIEW", "SENT_TO_A", "CLOSED"
        ]}

        dashboard_html = render_template("dashboard.html", mode="B", buckets=buckets, status_counts=status_counts, now=now)
        return render_template("admin_monitor.html", dept=dept, dashboard_html=dashboard_html,
                       total_users=total_users, active_users=active_users, admin_count=admin_count,
                       recent_email_issues=recent_email_issues)

    if dept == "C":
        pending = ReqModel.query.filter_by(status="PENDING_C_REVIEW").order_by(ReqModel.updated_at.desc()).all()
        dashboard_html = render_template("dashboard.html", mode="C", requests=pending, now=now)
        return render_template("admin_monitor.html", dept=dept, dashboard_html=dashboard_html,
                       total_users=total_users, active_users=active_users, admin_count=admin_count,
                       recent_email_issues=recent_email_issues)

    flash("Unknown department", "warning")
    return redirect(url_for("admin.monitor", dept="B"))



@admin_bp.route("/")
@login_required
def index():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    total_users = User.query.count()
    total_depts = Department.query.count()
    total_audit = AuditLog.query.count()
    return render_template('admin_index.html', total_users=total_users, total_depts=total_depts, total_audit=total_audit)


@admin_bp.route('/debug_workspace')
@login_required
def debug_workspace():
    # Small helper page that loads an internal path inside an iframe for debugging.
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    path = flask_request.args.get('path') or flask_request.args.get('url') or '/dashboard'
    # Basic safety: allow only internal paths starting with '/'
    try:
        path = unquote(path)
    except Exception:
        pass
    if not path.startswith('/'):
        path = '/dashboard'
    return render_template('admin_debug_workspace.html', path=path)


@admin_bp.route("/audit")
@login_required
def audit():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    q = flask_request.args.get("user")
    action = flask_request.args.get("action")
    audits = AuditLog.query.order_by(AuditLog.created_at.desc())
    if q:
        audits = audits.join(User, AuditLog.actor_user_id == User.id).filter(User.email.ilike(f"%{q}%"))
    if action:
        audits = audits.filter(AuditLog.action_type.ilike(f"%{action}%"))
    audits = audits.limit(200).all()
    return render_template("admin_audit.html", audits=audits)



@admin_bp.route('/assign_sso', methods=['GET', 'POST'])
@login_required
def assign_sso():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    form = SSOAssignForm()
    if form.validate_on_submit():
        raw = form.emails.data or ''
        emails = [e.strip().lower() for e in raw.splitlines() if e.strip()]
        dept = form.department.data
        updated = []
        skipped = []
        for em in emails:
            u = User.query.filter_by(email=em).first()
            if not u:
                skipped.append((em, 'not_found'))
                continue
            if not u.sso_sub:
                skipped.append((em, 'no_sso'))
                continue
            u.department = dept
            u.is_active = True
            updated.append(em)
        if updated:
            db.session.commit()
        flash(f'Assigned {len(updated)} users to Dept {dept}.', 'success')
        if skipped:
            flash('Skipped: ' + ', '.join([f'{e}({r})' for e, r in skipped]), 'warning')
        return redirect(url_for('admin.list_users'))

    return render_template('admin_assign_sso.html', form=form)



@admin_bp.route('/site_config', methods=['GET', 'POST'])
@login_required
def site_config():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    cfg = SiteConfig.query.first()
    form = SiteConfigForm(obj=cfg)
    if flask_request.method == 'GET' and cfg:
        form.navbar_banner.data = getattr(cfg, 'banner_html', None) or getattr(cfg, 'navbar_banner', None)
        try:
            rq = getattr(cfg, 'rolling_quotes', []) or []
            form.rolling_quotes.data = '\n'.join(rq) if isinstance(rq, list) else str(rq)
        except Exception:
            form.rolling_quotes.data = None
        form.show_banner.data = bool(getattr(cfg, 'rolling_quotes_enabled', getattr(cfg, 'show_banner', False)))

    if form.validate_on_submit():
        if not cfg:
            cfg = SiteConfig()
            db.session.add(cfg)
        # Support both current field names and legacy payload keys used by tests/UI.
        banner = form.navbar_banner.data
        if not banner:
            banner = flask_request.form.get('banner_html')

        rolling_enabled = bool(form.show_banner.data)
        if 'rolling_enabled' in flask_request.form:
            rolling_enabled = True

        rolling_input = form.rolling_quotes.data
        if not rolling_input:
            rolling_input = flask_request.form.get('rolling_csv')

        cfg.banner_html = banner or None
        cfg.rolling_quotes_enabled = rolling_enabled
        cfg.rolling_quotes = rolling_input or None
        db.session.commit()
        flash('Site configuration saved.', 'success')
        return redirect(url_for('admin.site_config'))

    return render_template('admin_site_config.html', form=form, cfg=cfg)


@admin_bp.route('/notifications_retention', methods=['GET', 'POST'])
@login_required
def notifications_retention():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    cfg = NotificationRetention.get()
    form = NotificationRetentionForm()
    if flask_request.method == 'GET':
        # prefill form
        form.retain_until_eod.data = bool(getattr(cfg, 'retain_until_eod', True))
        if cfg and cfg.clear_after_read_seconds is not None:
            secs = int(cfg.clear_after_read_seconds)
            if secs == 0:
                form.clear_after_choice.data = 'immediate'
            elif secs == 300:
                form.clear_after_choice.data = '5m'
            elif secs == 1800:
                form.clear_after_choice.data = '30m'
            elif secs == 3600:
                form.clear_after_choice.data = '1h'
            elif secs == 86400:
                form.clear_after_choice.data = '24h'
            else:
                days = max(1, min(7, int(secs / 86400)))
                form.clear_after_choice.data = 'custom'
                form.custom_days.data = days
        else:
            form.clear_after_choice.data = 'eod'
        form.max_notifications_per_user.data = int(getattr(cfg, 'max_notifications_per_user', 20) or 20)

    if form.validate_on_submit():
        if not cfg:
            cfg = NotificationRetention()
            db.session.add(cfg)

        cfg.retain_until_eod = bool(form.retain_until_eod.data)
        choice = form.clear_after_choice.data
        if choice == 'eod':
            cfg.clear_after_read_seconds = None
        elif choice == 'immediate':
            cfg.clear_after_read_seconds = 0
        elif choice == '5m':
            cfg.clear_after_read_seconds = 300
        elif choice == '30m':
            cfg.clear_after_read_seconds = 1800
        elif choice == '1h':
            cfg.clear_after_read_seconds = 3600
        elif choice == '24h':
            cfg.clear_after_read_seconds = 86400
        elif choice == 'custom':
            days = int(form.custom_days.data or 1)
            if days < 1:
                days = 1
            if days > 7:
                days = 7
            cfg.clear_after_read_seconds = days * 86400
            cfg.retain_until_eod = False

        maxn = int(form.max_notifications_per_user.data or 20)
        if maxn < 1:
            maxn = 1
        if maxn > 20:
            maxn = 20
        cfg.max_notifications_per_user = maxn
        cfg.max_retention_days = 7

        db.session.commit()
        flash('Notification retention updated.', 'success')
        return redirect(url_for('admin.notifications_retention'))

    return render_template('admin_notifications_retention.html', form=form, cfg=cfg)


@admin_bp.route('/special_email', methods=['GET', 'POST'])
@login_required
def special_email():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    from .forms import SpecialEmailConfigForm
    cfg = None
    try:
        from ..models import SpecialEmailConfig
        cfg = SpecialEmailConfig.get()
    except Exception:
        cfg = None

    form = SpecialEmailConfigForm()
    if flask_request.method == 'GET' and cfg:
        form.nudge_enabled.data = bool(getattr(cfg, 'nudge_enabled', False))
        form.nudge_interval_hours.data = int(getattr(cfg, 'nudge_interval_hours', 24) or 24)
        form.nudge_min_delay_hours.data = int(getattr(cfg, 'nudge_min_delay_hours', 4) or 4)

    if form.validate_on_submit():
        if not cfg:
            from ..models import SpecialEmailConfig
            cfg = SpecialEmailConfig()
            db.session.add(cfg)

        cfg.nudge_enabled = bool(form.nudge_enabled.data)
        cfg.nudge_interval_hours = int(form.nudge_interval_hours.data or 24)
        # enforce minimum allowed (4 hours); admin may only extend beyond this
        try:
            requested = int(form.nudge_min_delay_hours.data or 4)
        except Exception:
            requested = 4
        if requested < 4:
            requested = 4
            flash('Minimum nudge delay cannot be less than 4 hours; adjusted to 4.', 'warning')
        cfg.nudge_min_delay_hours = requested

        db.session.commit()
        flash('Nudge / special email settings saved.', 'success')
        return redirect(url_for('admin.special_email'))

    return render_template('admin_special_email.html', form=form, cfg=cfg)


@admin_bp.route('/feature_flags', methods=['GET', 'POST'])
@login_required
def feature_flags():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    from .forms import FeatureFlagsForm
    flags = FeatureFlags.get()
    form = FeatureFlagsForm()
    if flask_request.method == 'GET':
        form.enable_notifications.data = bool(getattr(flags, 'enable_notifications', True))
        form.enable_nudges.data = bool(getattr(flags, 'enable_nudges', True))
        form.allow_user_nudges.data = bool(getattr(flags, 'allow_user_nudges', False))

    if form.validate_on_submit():
        flags.enable_notifications = bool(form.enable_notifications.data)
        flags.enable_nudges = bool(form.enable_nudges.data)
        flags.allow_user_nudges = bool(form.allow_user_nudges.data)
        db.session.commit()
        flash('Feature flags updated.', 'success')
        return redirect(url_for('admin.feature_flags'))

    return render_template('admin_feature_flags.html', form=form, flags=flags)


@admin_bp.route('/reject_request_config', methods=['GET', 'POST'])
@login_required
def reject_request_config():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    from .forms import RejectRequestConfigForm
    cfg = RejectRequestConfig.get()
    form = RejectRequestConfigForm()

    if flask_request.method == 'GET':
        form.enabled.data = bool(getattr(cfg, 'enabled', True))
        form.button_label.data = getattr(cfg, 'button_label', 'Reject Request') or 'Reject Request'
        form.rejection_message.data = getattr(cfg, 'rejection_message', None)
        form.dept_a_enabled.data = bool(getattr(cfg, 'dept_a_enabled', False))
        form.dept_b_enabled.data = bool(getattr(cfg, 'dept_b_enabled', True))
        form.dept_c_enabled.data = bool(getattr(cfg, 'dept_c_enabled', False))

    if form.validate_on_submit():
        cfg.enabled = bool(form.enabled.data)
        cfg.button_label = (form.button_label.data or 'Reject Request').strip()[:120]
        cfg.rejection_message = (form.rejection_message.data or '').strip() or None
        cfg.dept_a_enabled = bool(form.dept_a_enabled.data)
        cfg.dept_b_enabled = bool(form.dept_b_enabled.data)
        cfg.dept_c_enabled = bool(form.dept_c_enabled.data)
        db.session.commit()
        flash('Reject request configuration updated.', 'success')
        return redirect(url_for('admin.reject_request_config'))

    return render_template('admin_reject_request_config.html', form=form, cfg=cfg)


@admin_bp.route('/departments')
@login_required
def list_departments():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    depts = Department.query.order_by(Department.code).all()
    return render_template('admin_departments.html', departments=depts)


@admin_bp.route('/status_options')
@login_required
def list_status_options():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    opts = StatusOption.query.order_by(StatusOption.code).all()
    return render_template('admin_status_options.html', status_options=opts)


@admin_bp.route('/status_options/new', methods=['GET', 'POST'])
@login_required
def create_status_option():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    from .forms import StatusOptionForm
    form = StatusOptionForm()
    if form.validate_on_submit():
        code = form.code.data.strip()
        opt = StatusOption(
            code=code,
            label=form.label.data.strip(),
            target_department=(form.target_department.data or None),
            notify_enabled=bool(form.notify_enabled.data),
            notify_on_transfer_only=bool(form.notify_on_transfer_only.data),
            email_enabled=bool(getattr(form, 'email_enabled', False).data if getattr(form, 'email_enabled', None) else False),
        )
        db.session.add(opt)
        db.session.commit()
        flash('Status option created.', 'success')
        return redirect(url_for('admin.list_status_options'))
    return render_template('admin_status_edit.html', form=form)


@admin_bp.route('/status_options/<int:opt_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_status_option(opt_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    from .forms import StatusOptionForm
    opt = StatusOption.query.get_or_404(opt_id)
    form = StatusOptionForm(obj=opt)
    if form.validate_on_submit():
        opt.code = form.code.data.strip()
        opt.label = form.label.data.strip()
        opt.target_department = form.target_department.data or None
        opt.notify_enabled = bool(form.notify_enabled.data)
        opt.notify_on_transfer_only = bool(form.notify_on_transfer_only.data)
        opt.email_enabled = bool(getattr(form, 'email_enabled', False).data if getattr(form, 'email_enabled', None) else False)
        db.session.commit()
        flash('Status option updated.', 'success')
        return redirect(url_for('admin.list_status_options'))
    return render_template('admin_status_edit.html', form=form, opt=opt)


@admin_bp.route('/status_options/<int:opt_id>/delete', methods=['POST'])
@login_required
def delete_status_option(opt_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    opt = StatusOption.query.get_or_404(opt_id)
    db.session.delete(opt)
    db.session.commit()
    flash('Status option deleted.', 'success')
    return redirect(url_for('admin.list_status_options'))


@admin_bp.route('/dept_editors')
@login_required
def list_dept_editors():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    editors = DepartmentEditor.query.order_by(DepartmentEditor.department, DepartmentEditor.assigned_at.desc()).all()
    return render_template('admin_dept_editors.html', editors=editors)


@admin_bp.route('/integrations')
@login_required
def list_integrations():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    ints = IntegrationConfig.query.order_by(IntegrationConfig.department, IntegrationConfig.kind).all()
    return render_template('admin_integrations.html', integrations=ints)


@admin_bp.route('/buckets/import_default', methods=['POST'])
@login_required
def import_default_buckets():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    # Recommended default buckets for Dept B (used by tests)
    try:
        # In Progress bucket
        b = StatusBucket.query.filter_by(name='In Progress', department_name='B').first()
        if not b:
            b = StatusBucket(name='In Progress', department_name='B', order=0, active=True)
            db.session.add(b)
            db.session.flush()
            bs = BucketStatus(bucket_id=b.id, status_code='B_IN_PROGRESS', order=0)
            db.session.add(bs)

        # Waiting bucket
        w = StatusBucket.query.filter_by(name='Waiting', department_name='B').first()
        if not w:
            w = StatusBucket(name='Waiting', department_name='B', order=1, active=True)
            db.session.add(w)
            db.session.flush()
            ws = BucketStatus(bucket_id=w.id, status_code='WAITING_ON_A_RESPONSE', order=0)
            db.session.add(ws)

        db.session.commit()
        flash('Imported recommended buckets.', 'success')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to import default buckets')
        flash('Failed to import buckets.', 'danger')
    return redirect(url_for('admin.list_departments'))


@admin_bp.route('/integrations/new', methods=['GET', 'POST'])
@login_required
def create_integration():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    from .forms import IntegrationConfigForm
    form = IntegrationConfigForm()
    if form.validate_on_submit():
        ic = IntegrationConfig(department=form.department.data, kind=form.kind.data, enabled=bool(form.enabled.data), config=(form.config_json.data or None))
        db.session.add(ic)
        db.session.commit()
        flash('Integration saved.', 'success')
        return redirect(url_for('admin.list_integrations'))
    return render_template('admin_integration_edit.html', form=form)


@admin_bp.route('/integrations/<int:int_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_integration(int_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    from .forms import IntegrationConfigForm
    ic = IntegrationConfig.query.get_or_404(int_id)
    form = IntegrationConfigForm(obj=ic)
    if form.validate_on_submit():
        ic.department = form.department.data
        ic.kind = form.kind.data
        ic.enabled = bool(form.enabled.data)
        ic.config = form.config_json.data or None
        db.session.commit()
        flash('Integration updated.', 'success')
        return redirect(url_for('admin.list_integrations'))
    return render_template('admin_integration_edit.html', form=form, integration=ic)


@admin_bp.route('/integrations/<int:int_id>/delete', methods=['POST'])
@login_required
def delete_integration(int_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    ic = IntegrationConfig.query.get_or_404(int_id)
    db.session.delete(ic)
    db.session.commit()
    flash('Integration removed.', 'success')
    return redirect(url_for('admin.list_integrations'))


@admin_bp.route('/dept_editors/new', methods=['GET', 'POST'])
@login_required
def create_dept_editor():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    from .forms import DepartmentEditorForm
    form = DepartmentEditorForm()
    # populate user choices
    form.user_id.choices = [(u.id, u.email) for u in User.query.order_by(User.email).all()]
    if form.validate_on_submit():
        de = DepartmentEditor(user_id=form.user_id.data, department=form.department.data, can_edit=bool(form.can_edit.data))
        db.session.add(de)
        db.session.commit()
        flash('Department editor created.', 'success')
        return redirect(url_for('admin.list_dept_editors'))
    return render_template('admin_dept_editor_edit.html', form=form)


@admin_bp.route('/dept_editors/<int:de_id>/delete', methods=['POST'])
@login_required
def delete_dept_editor(de_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    de = DepartmentEditor.query.get_or_404(de_id)
    db.session.delete(de)
    db.session.commit()
    flash('Department editor removed.', 'success')
    return redirect(url_for('admin.list_dept_editors'))


@admin_bp.route('/departments/new', methods=['GET', 'POST'])
@login_required
def create_department():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    form = DepartmentForm()
    if form.validate_on_submit():
        d = Department(code=form.code.data.upper(), label=form.name.data, description=None, is_active=bool(form.active.data), order=int(form.order.data or 0))
        db.session.add(d)
        db.session.commit()
        flash('Department created.', 'success')
        return redirect(url_for('admin.list_departments'))
    return render_template('admin_department_edit.html', form=form)


@admin_bp.route('/departments/<int:dept_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_department(dept_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    d = Department.query.get_or_404(dept_id)
    form = DepartmentForm(obj=d)
    if form.validate_on_submit():
        d.code = form.code.data.upper()
        d.label = form.name.data
        d.order = int(form.order.data or 0)
        d.is_active = bool(form.active.data)
        db.session.commit()
        flash('Department updated.', 'success')
        return redirect(url_for('admin.list_departments'))
    return render_template('admin_department_edit.html', form=form, dept=d)


@admin_bp.route('/departments/<int:dept_id>/delete', methods=['POST'])
@login_required
def delete_department(dept_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    d = Department.query.get_or_404(dept_id)
    db.session.delete(d)
    db.session.commit()
    flash('Department deleted.', 'success')
    return jsonify({"ok": True})
