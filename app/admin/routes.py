from flask import Blueprint, render_template, redirect, url_for, flash, current_app, session
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import User
from .forms import AdminCreateUserForm, SiteConfigForm, DepartmentForm, SSOAssignForm
from ..models import Request as ReqModel, Artifact, Submission, SiteConfig, Department
from ..models import StatusOption, DepartmentEditor
from datetime import datetime, timedelta
from flask import request as flask_request
from ..models import Notification, AuditLog
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
    if form.validate_on_submit():
        if not cfg:
            cfg = SiteConfig()
            db.session.add(cfg)
        cfg.navbar_banner = form.navbar_banner.data or None
        cfg.show_banner = bool(form.show_banner.data)
        cfg.rolling_quotes = form.rolling_quotes.data or None
        db.session.commit()
        flash('Site configuration saved.', 'success')
        return redirect(url_for('admin.site_config'))

    return render_template('admin_site_config.html', form=form, cfg=cfg)


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
        opt = StatusOption(code=code, label=form.label.data.strip(), target_department=(form.target_department.data or None), notify_enabled=bool(form.notify_enabled.data), notify_on_transfer_only=bool(form.notify_on_transfer_only.data))
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
        d = Department(code=form.code.data.upper(), label=form.label.data, description=form.description.data, is_active=bool(form.is_active.data))
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
        d.label = form.label.data
        d.description = form.description.data
        d.is_active = bool(form.is_active.data)
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
    return redirect(url_for('admin.list_departments'))
