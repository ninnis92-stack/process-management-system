from flask import Blueprint, render_template, redirect, url_for, flash, current_app, session, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from ..extensions import db, get_or_404
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
import os
from werkzeug.utils import secure_filename
from ..models import Workflow
from .forms import WorkflowForm
from .forms import StatusBucketForm
from .forms import FormTemplateAdminForm, FormFieldInlineForm
from .forms import DepartmentAssignmentForm
from .forms import BulkDepartmentAssignForm
from ..models import FormTemplate, FormField, DepartmentFormAssignment
from .forms import FieldVerificationForm
from ..models import FieldVerification
from ..models import UserDepartment

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
        is_admin = (getattr(form, 'role', None) and form.role.data == 'admin') or bool(form.is_admin.data)

        existing = User.query.filter_by(email=email).first()
        if existing:
            existing.name = name or existing.name
            existing.department = dept
            if form.password.data:
                existing.password_hash = generate_password_hash(pw, method="pbkdf2:sha256")
            existing.is_active = is_active
            existing.is_admin = is_admin
            db.session.commit()
            flash(f"Updated user {email}.", "success")
            return redirect(url_for("admin.list_users"))

        u = User(
            email=email,
            name=name,
            department=dept,
            password_hash=generate_password_hash(pw, method="pbkdf2:sha256"),
            is_active=is_active,
            is_admin=is_admin,
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

    u = get_or_404(User, user_id)
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
        u.is_admin = (getattr(form, 'role', None) and form.role.data == 'admin') or bool(form.is_admin.data)
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

    u = get_or_404(User, user_id)
    db.session.delete(u)
    db.session.commit()
    flash(f"Deleted user {u.email}.", "success")
    return redirect(url_for("admin.list_users"))


@admin_bp.route('/users/<int:user_id>/departments', methods=['GET', 'POST'])
@login_required
def manage_user_departments(user_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    u = get_or_404(User, user_id)
    # Supported department codes (keep in sync with models/choices)
    choices = ['A', 'B', 'C']

    if flask_request.method == 'POST':
        selected = flask_request.form.getlist('departments') or []
        selected = [s.strip().upper() for s in selected if s and s.strip()]

        # Remove existing assignments not in selected
        existing = {ud.department: ud for ud in getattr(u, 'departments', [])}
        for dept_code, ud in list(existing.items()):
            if dept_code not in selected:
                try:
                    db.session.delete(ud)
                except Exception:
                    db.session.rollback()

        # Add any new assignments
        for dept in selected:
            if dept == getattr(u, 'department', None):
                # primary department should not be duplicated as UserDepartment
                continue
            if dept not in existing:
                try:
                    new = UserDepartment(user_id=u.id, department=dept)
                    db.session.add(new)
                except Exception:
                    db.session.rollback()

        try:
            db.session.commit()
            flash('Updated department assignments.', 'success')
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            flash('Failed to save assignments.', 'danger')

        return redirect(url_for('admin.list_users'))

    # GET: show current assignments
    assigned = [ud.department for ud in getattr(u, 'departments', [])]
    return render_template('admin_user_departments.html', user=u, choices=choices, assigned=assigned)



@admin_bp.route('/users/<int:user_id>/impersonate', methods=['POST'])
@login_required


def impersonate_user(user_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    if current_user.id == user_id:
        flash('Cannot impersonate yourself.', 'warning')
        return redirect(url_for('admin.list_users'))

    target = get_or_404(User, user_id)
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


@admin_bp.route('/set_self_admin', methods=['POST'])
@login_required
def set_self_admin():
    """Allow a logged-in user to mark their account as admin when enabled via config.

    This action is gated by the `ALLOW_SELF_ADMIN` config flag to avoid accidental
    elevation in production environments.
    """
    if not current_app.config.get('ALLOW_SELF_ADMIN'):
        flash('Self-admin feature is not enabled on this instance.', 'danger')
        return redirect(flask_request.referrer or url_for('requests.dashboard'))

    # mark the current user as admin
    current_user.is_admin = True
    try:
        db.session.commit()
        flash('Your account has been updated to admin.', 'success')
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash('Failed to update admin status.', 'danger')

    return redirect(flask_request.referrer or url_for('admin.index'))



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
        # Use department-scoped queries so monitoring honors handoffs as well
        from ..utils.dept_scope import scope_requests_for_department
        base_b = scope_requests_for_department(ReqModel.query, 'B')
        buckets = {
            "New from A": base_b.filter(ReqModel.status == "NEW_FROM_A").order_by(ReqModel.updated_at.desc()).all(),
            "In progress by Department B": base_b.filter(ReqModel.status == "B_IN_PROGRESS").order_by(ReqModel.updated_at.desc()).all(),
            "Pending review from Department A": base_b.filter(ReqModel.status == "WAITING_ON_A_RESPONSE").order_by(ReqModel.updated_at.desc()).all(),
            "Needs changes": base_b.filter(ReqModel.status == "C_NEEDS_CHANGES").order_by(ReqModel.updated_at.desc()).all(),
            "Exec approval required": base_b.filter(ReqModel.status == "EXEC_APPROVAL").order_by(ReqModel.updated_at.desc()).all(),
            "Approved by C": base_b.filter(ReqModel.status == "C_APPROVED").order_by(ReqModel.updated_at.desc()).all(),
            "Final review": base_b.filter(ReqModel.status == "B_FINAL_REVIEW").order_by(ReqModel.updated_at.desc()).all(),
            "Sent to A": base_b.filter(ReqModel.status == "SENT_TO_A").order_by(ReqModel.updated_at.desc()).all(),
            "Under review by Department C": base_b.filter(ReqModel.status == "PENDING_C_REVIEW").order_by(ReqModel.updated_at.desc()).all(),
            "Closed": base_b.filter(ReqModel.status == "CLOSED").order_by(ReqModel.updated_at.desc()).all(),
            "All (B)": base_b.order_by(ReqModel.updated_at.desc()).all(),
        }

        # status counts for quick badges
        status_codes = ["B_IN_PROGRESS", "WAITING_ON_A_RESPONSE", "PENDING_C_REVIEW", "EXEC_APPROVAL", "B_FINAL_REVIEW", "SENT_TO_A", "CLOSED"]
        status_counts = {code: base_b.filter(ReqModel.status == code).count() for code in status_codes}

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


@admin_bp.route('/debug/cleanup', methods=['POST'])
@login_required
def debug_cleanup():
    # Admin-only maintenance endpoint to remove smoke or debug rows.
    if not _is_admin_user():
        return jsonify({'error': 'access_denied'}), 403

    confirm = flask_request.args.get('confirm') or flask_request.form.get('confirm')
    if str(confirm).lower() != 'true':
        return jsonify({'error': 'missing_confirm', 'note': 'set confirm=true'}), 400

    try:
        days = int(flask_request.args.get('days') or 0)
    except Exception:
        days = 0

    if days > 0:
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = ReqModel.query.filter(ReqModel.is_debug == True, ReqModel.created_at < cutoff).delete(synchronize_session=False)
    else:
        deleted = ReqModel.query.filter(ReqModel.title.like('SMOKE_%')).delete(synchronize_session=False)

    db.session.commit()
    return jsonify({'deleted': int(deleted)})


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
        return redirect(url_for('admin.list_users'))
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


@admin_bp.route('/bulk_assign_departments', methods=['GET', 'POST'])
@login_required
def bulk_assign_departments():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    form = BulkDepartmentAssignForm()
    if form.validate_on_submit():
        dept = (form.department.data or '').strip().upper()
        raw = form.emails.data or ''
        # Accept newline or comma separated
        parts = []
        for line in raw.splitlines():
            for token in line.split(','):
                token = token.strip().lower()
                if token:
                    parts.append(token)

        report_assigned = []
        report_missing = []
        report_skipped_primary = []
        report_skipped_existing = []
        report_errors = []

        for em in parts:
            try:
                u = User.query.filter_by(email=em).first()
            except Exception as exc:
                report_errors.append({'email': em, 'error': str(exc)})
                continue
            if not u:
                report_missing.append(em)
                continue

            if getattr(u, 'department', None) == dept:
                report_skipped_primary.append(em)
                continue

            existing = UserDepartment.query.filter_by(user_id=u.id, department=dept).first()
            if existing:
                report_skipped_existing.append(em)
                continue

            try:
                ud = UserDepartment(user_id=u.id, department=dept)
                db.session.add(ud)
                db.session.commit()
                report_assigned.append(em)
            except Exception as exc:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                report_errors.append({'email': em, 'error': str(exc)})

        return render_template('admin_bulk_assign_report.html', dept=dept,
                               assigned=report_assigned,
                               missing=report_missing,
                               skipped_primary=report_skipped_primary,
                               skipped_existing=report_skipped_existing,
                               errors=report_errors)

    return render_template('admin_bulk_assign_departments.html', form=form)



@admin_bp.route('/site_config', methods=['GET', 'POST'])
@login_required
def site_config():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    cfg = SiteConfig.query.first()
    form = SiteConfigForm(obj=cfg)
    if flask_request.method == 'GET' and cfg:
        form.brand_name.data = getattr(cfg, 'brand_name', None)
        form.theme_preset.data = (getattr(cfg, 'theme_preset', 'default') or 'default')
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

        cfg.brand_name = (form.brand_name.data or '').strip() or None
        cfg.theme_preset = (form.theme_preset.data or 'default').strip().lower()
        if cfg.theme_preset not in ('default', 'ocean', 'forest', 'sunset', 'midnight'):
            cfg.theme_preset = 'default'

        remove_logo = bool(form.clear_logo.data)
        uploaded_logo = flask_request.files.get('logo_upload')
        if remove_logo:
            cfg.logo_filename = None
        if uploaded_logo and uploaded_logo.filename:
            filename = secure_filename(uploaded_logo.filename)
            if filename:
                ext = os.path.splitext(filename)[1].lower()
                stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
                stored_name = f"logo_{stamp}{ext}"
                rel_dir = os.path.join('uploads', 'branding')
                static_dir = current_app.static_folder or os.path.join(current_app.root_path, 'static')
                abs_dir = os.path.join(static_dir, rel_dir)
                os.makedirs(abs_dir, exist_ok=True)
                uploaded_logo.save(os.path.join(abs_dir, stored_name))
                cfg.logo_filename = f"uploads/branding/{stored_name}"

        cfg.banner_html = banner or None
        cfg.rolling_quotes_enabled = rolling_enabled
        cfg.rolling_quotes = rolling_input or None
        db.session.commit()
        flash('Site configuration saved.', 'success')
        return redirect(url_for('admin.site_config'))

    return render_template('admin_site_config.html', form=form, cfg=cfg)


@admin_bp.route('/workflows')
@login_required
def list_workflows():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    wfs = Workflow.query.order_by(Workflow.name.asc()).all()
    return render_template('admin_workflows.html', workflows=wfs)


@admin_bp.route('/workflows/new', methods=['GET', 'POST'])
@login_required
def create_workflow():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    form = WorkflowForm()
    if form.validate_on_submit():
        wf = Workflow(
            name=form.name.data.strip(),
            description=(form.description.data or '').strip() or None,
            department_code=(form.department_code.data or None) or None,
            spec=None,
            active=bool(form.active.data),
        )
        # attempt to parse JSON if provided
        import json
        if form.spec_json.data:
            try:
                wf.spec = json.loads(form.spec_json.data)
            except Exception:
                flash('Invalid JSON for workflow spec.', 'danger')
                return render_template('admin_workflow_form.html', form=form)
        db.session.add(wf)
        db.session.commit()
        flash('Workflow created.', 'success')
        return redirect(url_for('admin.list_workflows'))
    return render_template('admin_workflow_form.html', form=form)


@admin_bp.route('/workflows/<int:wf_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_workflow(wf_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    wf = get_or_404(Workflow, wf_id)
    form = WorkflowForm(obj=wf)
    # prefill spec_json
    if flask_request.method == 'GET' and wf.spec is not None:
        import json
        try:
            form.spec_json.data = json.dumps(wf.spec, indent=2)
        except Exception:
            form.spec_json.data = str(wf.spec)

    if form.validate_on_submit():
        wf.name = form.name.data.strip()
        wf.description = (form.description.data or '').strip() or None
        wf.department_code = (form.department_code.data or None) or None
        wf.active = bool(form.active.data)
        if form.spec_json.data:
            import json
            try:
                wf.spec = json.loads(form.spec_json.data)
            except Exception:
                flash('Invalid JSON for workflow spec.', 'danger')
                return render_template('admin_workflow_form.html', form=form, wf=wf)
        else:
            wf.spec = None
        db.session.commit()
        flash('Workflow updated.', 'success')
        return redirect(url_for('admin.list_workflows'))
    return render_template('admin_workflow_form.html', form=form, wf=wf)


@admin_bp.route('/workflows/<int:wf_id>/delete', methods=['POST'])
@login_required
def delete_workflow(wf_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    wf = get_or_404(Workflow, wf_id)
    db.session.delete(wf)
    db.session.commit()
    flash('Workflow deleted.', 'success')
    return redirect(url_for('admin.list_workflows'))


@admin_bp.route('/templates')
@login_required
def list_templates():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    templates = FormTemplate.query.order_by(FormTemplate.created_at.desc()).all()
    return render_template('admin_templates.html', templates=templates)


@admin_bp.route('/templates/new', methods=['GET', 'POST'])
@login_required
def create_template():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    form = FormTemplateAdminForm()
    if form.validate_on_submit():
        t = FormTemplate(name=form.name.data.strip(), description=(form.description.data or '').strip() or None)
        db.session.add(t)
        db.session.commit()
        # create requested number of empty fields
        try:
            n = int(form.field_count.data or 0)
        except Exception:
            n = 0
        for i in range(max(0, n)):
            f = FormField(template_id=t.id, name=f'field_{i+1}', label=f'Field {i+1}', field_type='text', required=False)
            db.session.add(f)
        db.session.commit()
        flash('Template created. Edit fields as needed.', 'success')
        return redirect(url_for('admin.edit_template_fields', template_id=t.id))
    return render_template('admin_template_form.html', form=form)


@admin_bp.route('/templates/<int:template_id>/fields', methods=['GET', 'POST'])
@login_required
def edit_template_fields(template_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    t = get_or_404(FormTemplate, template_id)
    # Handle simple bulk update: inputs named field_<id>_label, field_<id>_required
    if flask_request.method == 'POST':
        for f in t.fields:
            lab = flask_request.form.get(f'field_{f.id}_label')
            nm = flask_request.form.get(f'field_{f.id}_name')
            req = flask_request.form.get(f'field_{f.id}_required')
            ft = flask_request.form.get(f'field_{f.id}_type')
            if lab is not None:
                f.label = lab.strip()
            if nm is not None:
                f.name = nm.strip() or f.name
            if ft is not None:
                f.field_type = ft
            f.required = bool(req)
            db.session.add(f)
        db.session.commit()
        flash('Fields updated.', 'success')
        return redirect(url_for('admin.list_templates'))

    # Render editing UI
    fields = sorted(list(t.fields), key=lambda ff: getattr(ff, 'created_at', getattr(ff, 'id', 0)))
    return render_template('admin_edit_template_fields.html', template=t, fields=fields)


@admin_bp.route('/fields/<int:field_id>/verification', methods=['GET', 'POST'])
@login_required
def edit_field_verification(field_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    f = get_or_404(FormField, field_id)
    # pick latest mapping if multiple
    fv = FieldVerification.query.filter_by(field_id=f.id).order_by(FieldVerification.created_at.desc()).first()
    form = FieldVerificationForm()
    if flask_request.method == 'GET' and fv:
        form.provider.data = fv.provider
        form.external_key.data = fv.external_key
        import json
        try:
            form.params_json.data = json.dumps(fv.params, indent=2) if fv.params is not None else ''
        except Exception:
            form.params_json.data = str(fv.params or '')
        try:
            form.triggers_auto_reject.data = bool(getattr(fv, 'triggers_auto_reject', False))
        except Exception:
            form.triggers_auto_reject.data = False

    if form.validate_on_submit():
        import json
        params = None
        if form.params_json.data:
            try:
                params = json.loads(form.params_json.data)
            except Exception:
                flash('Invalid JSON in params field.', 'danger')
                return render_template('admin_field_verification.html', form=form, field=f, fv=fv)

        # Replace existing mapping (simple policy: create new row)
        new = FieldVerification(
            field_id=f.id,
            provider=form.provider.data,
            external_key=(form.external_key.data or None),
            params=params,
            triggers_auto_reject=bool(form.triggers_auto_reject.data),
        )
        db.session.add(new)
        db.session.commit()
        flash('Field verification mapping saved.', 'success')
        return redirect(url_for('admin.edit_template_fields', template_id=f.template_id))

    return render_template('admin_field_verification.html', form=form, field=f, fv=fv)


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
    # Defensive: previous DB errors can leave the session in an aborted state
    # which causes subsequent queries to fail with InFailedSqlTransaction.
    try:
        db.session.rollback()
    except Exception:
        pass

    try:
        sso_users = User.query.filter(User.sso_sub.isnot(None)).order_by(User.email.asc()).all()
    except Exception:
        current_app.logger.exception('Failed querying SSO users for special_email admin page')
        try:
            db.session.rollback()
        except Exception:
            pass
        sso_users = []

    form.request_form_user_id.choices = [(0, '-- None --')] + [(u.id, f"{u.email} (Dept {u.department})") for u in sso_users]
    if flask_request.method == 'GET' and cfg:
        form.enabled.data = bool(getattr(cfg, 'enabled', False))
        form.request_form_email.data = getattr(cfg, 'request_form_email', None)
        form.request_form_user_id.data = int(getattr(cfg, 'request_form_user_id', 0) or 0)
        form.request_form_first_message.data = getattr(cfg, 'request_form_first_message', None)
        form.request_form_department.data = (getattr(cfg, 'request_form_department', 'A') or 'A')
        form.request_form_field_validation_enabled.data = bool(getattr(cfg, 'request_form_field_validation_enabled', False))
        form.request_form_auto_reject_oos_enabled.data = bool(getattr(cfg, 'request_form_auto_reject_oos_enabled', False))
        form.request_form_inventory_out_of_stock_notify_enabled.data = bool(getattr(cfg, 'request_form_inventory_out_of_stock_notify_enabled', False))
        form.request_form_inventory_out_of_stock_notify_mode.data = (getattr(cfg, 'request_form_inventory_out_of_stock_notify_mode', 'email') or 'email')
        form.request_form_inventory_out_of_stock_message.data = getattr(cfg, 'request_form_inventory_out_of_stock_message', None)
        form.nudge_enabled.data = bool(getattr(cfg, 'nudge_enabled', False))
        form.nudge_interval_hours.data = int(getattr(cfg, 'nudge_interval_hours', 24) or 24)
        form.nudge_min_delay_hours.data = int(getattr(cfg, 'nudge_min_delay_hours', 4) or 4)

    if form.validate_on_submit():
        if not cfg:
            from ..models import SpecialEmailConfig
            cfg = SpecialEmailConfig()
            db.session.add(cfg)

        cfg.enabled = bool(form.enabled.data)
        selected_owner_id = int(form.request_form_user_id.data or 0)
        selected_owner = db.session.get(User, selected_owner_id) if selected_owner_id else None
        if selected_owner and not selected_owner.sso_sub:
            selected_owner = None
            selected_owner_id = 0

        cfg.request_form_user_id = (selected_owner_id or None)
        manual_inbox = (form.request_form_email.data or '').strip() or None
        cfg.request_form_email = manual_inbox or (selected_owner.email if selected_owner else None)
        cfg.request_form_first_message = (form.request_form_first_message.data or '').strip() or None
        cfg.request_form_department = (form.request_form_department.data or 'A').strip().upper()
        if selected_owner:
            cfg.request_form_department = (selected_owner.department or cfg.request_form_department or 'A').strip().upper()
        if cfg.request_form_department not in ('A', 'B', 'C'):
            cfg.request_form_department = 'A'
        cfg.request_form_field_validation_enabled = bool(form.request_form_field_validation_enabled.data)
        cfg.request_form_auto_reject_oos_enabled = bool(form.request_form_auto_reject_oos_enabled.data)
        cfg.request_form_inventory_out_of_stock_notify_enabled = bool(form.request_form_inventory_out_of_stock_notify_enabled.data)
        cfg.request_form_inventory_out_of_stock_notify_mode = (form.request_form_inventory_out_of_stock_notify_mode.data or 'email').strip().lower()
        if cfg.request_form_inventory_out_of_stock_notify_mode not in ('notification', 'email', 'both'):
            cfg.request_form_inventory_out_of_stock_notify_mode = 'email'
        cfg.request_form_inventory_out_of_stock_message = (form.request_form_inventory_out_of_stock_message.data or '').strip() or None

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


@admin_bp.route('/email_routing')
@login_required
def email_routing_list():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    from ..models import EmailRouting
    rows = EmailRouting.query.order_by(EmailRouting.recipient_email.asc()).all()
    return render_template('admin_email_routing.html', rows=rows)


@admin_bp.route('/email_routing/new', methods=['GET', 'POST'])
@login_required
def email_routing_new():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    from .forms import EmailRoutingForm
    form = EmailRoutingForm()
    if form.validate_on_submit():
        from ..models import EmailRouting
        r = EmailRouting(recipient_email=form.recipient_email.data.strip().lower(), department_code=form.department_code.data.strip().upper())
        db.session.add(r)
        db.session.commit()
        flash('Email routing mapping created.', 'success')
        return redirect(url_for('admin.email_routing_list'))
    return render_template('admin_email_routing_form.html', form=form)


@admin_bp.route('/assignments')
@login_required
def list_assignments():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    rows = DepartmentFormAssignment.query.order_by(DepartmentFormAssignment.department_name.asc()).all()
    # load templates map for display
    templates = {t.id: t for t in FormTemplate.query.order_by(FormTemplate.name.asc()).all()}
    return render_template('admin_assignments.html', rows=rows, templates=templates)


@admin_bp.route('/assignments/new', methods=['GET', 'POST'])
@login_required
def new_assignment():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    form = DepartmentAssignmentForm()
    form.template_id.choices = [(t.id, t.name) for t in FormTemplate.query.order_by(FormTemplate.name.asc()).all()]
    if form.validate_on_submit():
        # ensure one assignment per department (replace existing)
        DepartmentFormAssignment.query.filter_by(department_name=form.department.data).delete()
        a = DepartmentFormAssignment(template_id=form.template_id.data, department_name=form.department.data)
        db.session.add(a)
        db.session.commit()
        flash('Template assigned to department.', 'success')
        return redirect(url_for('admin.list_assignments'))

    return render_template('admin_assignments.html', form=form, rows=[], templates={})


@admin_bp.route('/assignments/<int:assignment_id>/delete', methods=['POST'])
@login_required
def delete_assignment(assignment_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    a = get_or_404(DepartmentFormAssignment, assignment_id)
    db.session.delete(a)
    db.session.commit()
    flash('Assignment removed.', 'success')
    return redirect(url_for('admin.list_assignments'))


@admin_bp.route('/email_routing/<int:rid>/edit', methods=['GET', 'POST'])
@login_required
def email_routing_edit(rid: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    from ..models import EmailRouting
    r = get_or_404(EmailRouting, rid)
    from .forms import EmailRoutingForm
    form = EmailRoutingForm(obj=r)
    if form.validate_on_submit():
        r.recipient_email = form.recipient_email.data.strip().lower()
        r.department_code = form.department_code.data.strip().upper()
        db.session.commit()
        flash('Email routing mapping updated.', 'success')
        return redirect(url_for('admin.email_routing_list'))
    return render_template('admin_email_routing_form.html', form=form, edit=r)


@admin_bp.route('/email_routing/<int:rid>/delete', methods=['POST'])
@login_required
def email_routing_delete(rid: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    from ..models import EmailRouting
    r = get_or_404(EmailRouting, rid)
    db.session.delete(r)
    db.session.commit()
    flash('Email routing mapping deleted.', 'success')
    return redirect(url_for('admin.email_routing_list'))


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
        form.vibe_enabled.data = bool(getattr(flags, 'vibe_enabled', True))
        form.sso_admin_sync_enabled.data = bool(getattr(flags, 'sso_admin_sync_enabled', True))

    if form.validate_on_submit():
        flags.enable_notifications = bool(form.enable_notifications.data)
        flags.enable_nudges = bool(form.enable_nudges.data)
        flags.allow_user_nudges = bool(form.allow_user_nudges.data)
        flags.vibe_enabled = bool(form.vibe_enabled.data)
        flags.sso_admin_sync_enabled = bool(form.sso_admin_sync_enabled.data)
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
            screenshot_required=bool(getattr(form, 'screenshot_required', False).data if getattr(form, 'screenshot_required', None) else False),
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
    opt = get_or_404(StatusOption, opt_id)
    form = StatusOptionForm(obj=opt)
    if form.validate_on_submit():
        opt.code = form.code.data.strip()
        opt.label = form.label.data.strip()
        opt.target_department = form.target_department.data or None
        opt.notify_enabled = bool(form.notify_enabled.data)
        opt.notify_on_transfer_only = bool(form.notify_on_transfer_only.data)
        opt.email_enabled = bool(getattr(form, 'email_enabled', False).data if getattr(form, 'email_enabled', None) else False)
        opt.screenshot_required = bool(getattr(form, 'screenshot_required', False).data if getattr(form, 'screenshot_required', None) else False)
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
    opt = get_or_404(StatusOption, opt_id)
    db.session.delete(opt)
    db.session.commit()
    flash('Status option deleted.', 'success')
    return redirect(url_for('admin.list_status_options'))


@admin_bp.route('/status_options/<int:opt_id>/toggle_screenshot', methods=['POST'])
@login_required
def toggle_status_screenshot(opt_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    opt = get_or_404(StatusOption, opt_id)
    try:
        opt.screenshot_required = not bool(opt.screenshot_required)
        db.session.commit()
        flash('Screenshot requirement updated.', 'success')
    except Exception:
        db.session.rollback()
        flash('Failed to update screenshot requirement.', 'danger')
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


@admin_bp.route('/buckets')
@login_required
def list_buckets():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    buckets = StatusBucket.query.order_by(StatusBucket.department_name.asc().nullsfirst(), StatusBucket.order.asc()).all()
    return render_template('admin_buckets.html', buckets=buckets)


@admin_bp.route('/buckets/new', methods=['GET', 'POST'])
@login_required
def buckets_new():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    form = StatusBucketForm()
    # populate workflow choices (global + any department-scoped active workflows)
    wfs = Workflow.query.filter(Workflow.active == True).order_by(Workflow.name.asc()).all()
    form.workflow_id.choices = [(0, '-- None --')] + [(w.id, w.name + (f" (Dept {w.department_code})" if w.department_code else '')) for w in wfs]

    if form.validate_on_submit():
        b = StatusBucket(name=form.name.data.strip(), department_name=(form.department_name.data or None) or None,
                         order=int(form.order.data or 0), active=bool(form.active.data))
        # assign workflow if selected
        try:
            sel = int(form.workflow_id.data or 0)
        except Exception:
            sel = 0
        if sel:
            b.workflow_id = sel
        db.session.add(b)
        db.session.commit()
        flash('Bucket created.', 'success')
        return redirect(url_for('admin.list_buckets'))
    return render_template('admin_bucket_form.html', form=form)


@admin_bp.route('/buckets/<int:bucket_id>/edit', methods=['GET', 'POST'])
@login_required
def buckets_edit(bucket_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    b = get_or_404(StatusBucket, bucket_id)
    form = StatusBucketForm(obj=b)
    # populate workflow choices scoped to department (or global)
    if b.department_name:
        wfs = Workflow.query.filter((Workflow.department_code == None) | (Workflow.department_code == b.department_name)).filter(Workflow.active == True).order_by(Workflow.name.asc()).all()
    else:
        wfs = Workflow.query.filter(Workflow.active == True).order_by(Workflow.name.asc()).all()
    form.workflow_id.choices = [(0, '-- None --')] + [(w.id, w.name + (f" (Dept {w.department_code})" if w.department_code else '')) for w in wfs]
    # prefill selected workflow in form when GET
    if flask_request.method == 'GET':
        try:
            form.workflow_id.data = int(b.workflow_id) if b.workflow_id else 0
        except Exception:
            form.workflow_id.data = 0

    if form.validate_on_submit():
        b.name = form.name.data.strip()
        b.department_name = (form.department_name.data or None) or None
        b.order = int(form.order.data or 0)
        b.active = bool(form.active.data)
        try:
            sel = int(form.workflow_id.data or 0)
        except Exception:
            sel = 0
        b.workflow_id = sel or None
        db.session.commit()
        flash('Bucket updated.', 'success')
        # handle bulk-add statuses if provided
        bulk = (form.bulk_statuses.data or '').strip()
        if bulk:
            lines = [l.strip() for l in bulk.splitlines() if l.strip()]
            if lines:
                # compute next order base
                existing = b.statuses.order_by(BucketStatus.order.desc()).first()
                base = existing.order + 1 if existing else 0
                for idx, code in enumerate(lines):
                    ns = BucketStatus(bucket_id=b.id, status_code=code, order=base + idx)
                    db.session.add(ns)
                db.session.commit()
                flash(f'Added {len(lines)} statuses to bucket.', 'success')
        return redirect(url_for('admin.list_buckets'))

    # handle adding a new status code via POST param (supports select or free text)
    if flask_request.method == 'POST' and (flask_request.form.get('new_status_code') or flask_request.form.get('new_status_code_select')):
        code = (flask_request.form.get('new_status_code_select') or flask_request.form.get('new_status_code') or '').strip()
        try:
            ordv = int(flask_request.form.get('new_status_order') or 0)
        except Exception:
            ordv = 0
        if code:
            ns = BucketStatus(bucket_id=b.id, status_code=code, order=ordv)
            db.session.add(ns)
            db.session.commit()
            flash('Added status to bucket.', 'success')
        return redirect(url_for('admin.buckets_edit', bucket_id=b.id))

    statuses = b.statuses.order_by(BucketStatus.order.asc()).all()

    # Load available status options and workflows scoped to this bucket's department
    if b.department_name:
        status_opts = StatusOption.query.filter((StatusOption.target_department == None) | (StatusOption.target_department == b.department_name)).order_by(StatusOption.code.asc()).all()
        workflows = Workflow.query.filter((Workflow.department_code == None) | (Workflow.department_code == b.department_name)).filter(Workflow.active == True).order_by(Workflow.name.asc()).all()
    else:
        status_opts = StatusOption.query.order_by(StatusOption.code.asc()).all()
        workflows = Workflow.query.filter(Workflow.active == True).order_by(Workflow.name.asc()).all()

    return render_template('admin_bucket_form.html', form=form, bucket=b, statuses=statuses, status_options=status_opts, workflows=workflows)


@admin_bp.route('/buckets/<int:bucket_id>/delete', methods=['POST'])
@login_required
def buckets_delete(bucket_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    b = get_or_404(StatusBucket, bucket_id)
    db.session.delete(b)
    db.session.commit()
    flash('Bucket deleted.', 'success')
    return redirect(url_for('admin.list_buckets'))


@admin_bp.route('/buckets/<int:bucket_id>/status/<int:status_id>/delete', methods=['POST'])
@login_required
def buckets_status_delete(bucket_id: int, status_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    s = get_or_404(BucketStatus, status_id)
    db.session.delete(s)
    db.session.commit()
    flash('Bucket status removed.', 'success')
    return redirect(url_for('admin.buckets_edit', bucket_id=bucket_id))


@admin_bp.route('/buckets/<int:bucket_id>/reorder_statuses', methods=['POST'])
@login_required
def buckets_reorder_statuses(bucket_id: int):
    if not _is_admin_user():
        return jsonify({'error': 'access_denied'}), 403

    b = get_or_404(StatusBucket, bucket_id)
    try:
        payload = flask_request.get_json(force=True)
    except Exception:
        payload = None
    if not payload or 'order' not in payload or not isinstance(payload.get('order'), list):
        return jsonify({'error': 'invalid_payload'}), 400

    ids = [int(x) for x in payload.get('order') if str(x).isdigit()]
    # ensure all ids belong to this bucket
    items = {s.id: s for s in BucketStatus.query.filter(BucketStatus.bucket_id == b.id, BucketStatus.id.in_(ids)).all()}
    # apply new order
    for idx, sid in enumerate(ids):
        s = items.get(sid)
        if s:
            s.order = int(idx)
            db.session.add(s)
    db.session.commit()
    return jsonify({'ok': True})


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
    ic = get_or_404(IntegrationConfig, int_id)
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
    ic = get_or_404(IntegrationConfig, int_id)
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
    de = get_or_404(DepartmentEditor, de_id)
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
    d = get_or_404(Department, dept_id)
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
    d = get_or_404(Department, dept_id)
    db.session.delete(d)
    db.session.commit()
    flash('Department deleted.', 'success')
    return jsonify({"ok": True})
