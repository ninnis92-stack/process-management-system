from flask import Blueprint, render_template, redirect, url_for, flash, current_app, session, request
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import User
from .forms import AdminCreateUserForm, AdminSpecialEmailsForm
from ..models import Request as ReqModel, Artifact, Submission, SpecialEmailConfig
from ..models import AppTheme
from datetime import datetime, timedelta
from flask import request as flask_request
from ..models import Notification, AuditLog
from ..models import FormTemplate, FormField, FormFieldOption, DepartmentFormAssignment, VerificationRule, IntegrationKey
from ..models import Department, SiteConfig
from urllib.parse import unquote
from .. import notifcations as notifications
from ..requests_bp.workflow import owner_for_status
from datetime import datetime, timedelta
from flask import jsonify
from .forms import FormTemplateForm, FormFieldForm, DepartmentAssignmentForm, VerificationRuleForm, DepartmentFormAdmin, SiteConfigForm
from ..admin.forms import FormTemplateForm as _noop_import
import json
import os
from .forms import BucketForm, BucketStatusForm

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


@admin_bp.post('/debug/simulate_create')
@login_required
def debug_simulate_create():
    if not _is_admin_user():
        return jsonify({'ok': False, 'error': 'access_denied'}), 403

    title = flask_request.form.get('title') or 'Simulated Request'
    priority = flask_request.form.get('priority') or 'medium'
    due_days = int(flask_request.form.get('due_days') or 0)

    now = datetime.utcnow()
    due_at = (now + timedelta(days=due_days)) if due_days else None

    req = ReqModel(
        title=title,
        request_type='both',
        pricebook_status='unknown',
        description='Simulated by admin debug workspace',
        priority=priority,
        requires_c_review=False,
        status='NEW_FROM_A',
        owner_department='B',
        submitter_type='user',
        created_by_user_id=current_user.id,
        due_at=due_at,
        is_debug=True,
    )
    db.session.add(req)
    db.session.commit()

    url = url_for('requests.request_detail', request_id=req.id)
    return jsonify({'ok': True, 'request_id': req.id, 'url': url})


@admin_bp.post('/debug/simulate_overdue')
@login_required
def debug_simulate_overdue():
    if not _is_admin_user():
        return jsonify({'ok': False, 'error': 'access_denied'}), 403

    req_id = flask_request.form.get('request_id')
    if not req_id:
        return jsonify({'ok': False, 'error': 'missing_request_id'}), 400

    req = ReqModel.query.get(int(req_id))
    if not req:
        return jsonify({'ok': False, 'error': 'not_found'}), 404

    # Only allow operating on debug requests from this endpoint
    if not getattr(req, 'is_debug', False):
        return jsonify({'ok': False, 'error': 'not_debug_request'}), 403

    # set due date to past to simulate overdue
    req.due_at = datetime.utcnow() - timedelta(days=2)
    db.session.commit()
    return jsonify({'ok': True, 'request_id': req.id})


@admin_bp.post('/debug/simulate_flow')
@login_required
def debug_simulate_flow():
    if not _is_admin_user():
        return jsonify({'ok': False, 'error': 'access_denied'}), 403

    req_id = flask_request.form.get('request_id')
    mode = flask_request.form.get('mode') or 'step'  # 'step' or 'full'
    if not req_id:
        return jsonify({'ok': False, 'error': 'missing_request_id'}), 400
    req = ReqModel.query.get(int(req_id))
    if not req:
        return jsonify({'ok': False, 'error': 'not_found'}), 404

    # Only allow operating on debug requests from this endpoint
    if not getattr(req, 'is_debug', False):
        return jsonify({'ok': False, 'error': 'not_debug_request'}), 403

    # demo path
    path = [
        'NEW_FROM_A', 'B_IN_PROGRESS', 'PENDING_C_REVIEW', 'C_APPROVED',
        'B_FINAL_REVIEW', 'SENT_TO_A', 'CLOSED'
    ]

    try:
        cur = req.status
        idx = path.index(cur) if cur in path else 0
    except Exception:
        idx = 0

    def _apply_status(r, new_status):
        r.status = new_status
        r.owner_department = owner_for_status(new_status)
        # audit log
        entry = AuditLog(request_id=r.id, actor_type='user', actor_user_id=current_user.id,
                         actor_label=current_user.email, action_type='status_change',
                         from_status=cur, to_status=new_status, note='Simulated status change by admin')
        db.session.add(entry)
        # notify new owners
        recipients = [u for u in User.query.filter_by(department=r.owner_department, is_active=True).all()]
        try:
            notifications.notify_users(recipients, title=f"Simulated: Request #{r.id} -> {new_status}", body=r.title,
                                       url=url_for('requests.request_detail', request_id=r.id), ntype='status_change', request_id=r.id)
        except Exception:
            current_app.logger.exception('Failed to send simulated notifications')

    if mode == 'full':
        # apply all remaining steps
        for next_status in path[idx+1:]:
            _apply_status(req, next_status)
        db.session.commit()
        return jsonify({'ok': True, 'request_id': req.id, 'status': req.status})
    else:
        # single step
        if idx+1 < len(path):
            next_status = path[idx+1]
            _apply_status(req, next_status)
            db.session.commit()
            return jsonify({'ok': True, 'request_id': req.id, 'status': req.status})
        else:
            return jsonify({'ok': False, 'error': 'already_final'})


@admin_bp.post('/debug/cleanup')
@login_required
def debug_cleanup():
    """Delete `is_debug` requests older than `days` (requires confirm=true).

    Usage (POST or GET): /admin/debug/cleanup?days=7&confirm=true
    """
    if not _is_admin_user():
        return jsonify({'ok': False, 'error': 'access_denied'}), 403

    try:
        days = int(flask_request.form.get('days') or flask_request.args.get('days') or 7)
    except Exception:
        days = 7

    confirm = (flask_request.form.get('confirm') or flask_request.args.get('confirm') or 'false').lower()
    if confirm != 'true':
        return jsonify({'ok': False, 'error': 'confirm_required', 'message': 'Pass confirm=true to actually delete.'}), 400

    cutoff = datetime.utcnow() - timedelta(days=days)

    # Find debug requests older than cutoff
    old_reqs = ReqModel.query.filter(ReqModel.is_debug == True, ReqModel.created_at < cutoff).all()
    deleted = 0
    for r in old_reqs:
        try:
            db.session.delete(r)
            deleted += 1
        except Exception:
            current_app.logger.exception('Failed to delete debug request %s', getattr(r, 'id', None))

    db.session.commit()

    # Record an audit entry for cleanup
    try:
        entry = AuditLog(request_id=None, actor_type='user', actor_user_id=current_user.id,
                         actor_label=current_user.email, action_type='debug_cleanup',
                         note=f'Deleted {deleted} debug requests older than {days} days', event_ts=datetime.utcnow())
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to write debug cleanup audit log')

    return jsonify({'ok': True, 'deleted': deleted})


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


@admin_bp.route('/special_emails', methods=['GET', 'POST'])
@login_required
def special_emails():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    cfg = SpecialEmailConfig.get()
    form = AdminSpecialEmailsForm()

    # Populate possible user choices for SSO-linked selection
    users = [(0, "-- none --")] + [(u.id, u.email) for u in User.query.order_by(User.email).all()]
    form.help_user.choices = users
    form.request_form_user.choices = users
    # Prefill nudge choices
    form.nudge_enable.choices = [("false", "Off"), ("true", "On")]
    # runtime integration toggles (boolean fields)
    form.email_toggle.data = bool(cfg.email_override) if hasattr(cfg, 'email_override') else False
    form.ticketing_toggle.data = bool(cfg.ticketing_override) if hasattr(cfg, 'ticketing_override') else False
    form.inventory_toggle.data = bool(cfg.inventory_override) if hasattr(cfg, 'inventory_override') else False

    if form.validate_on_submit():
        cfg.enabled = True if form.enable_feature.data == 'true' else False
        cfg.help_email = (form.help_email.data or '').strip().lower() or None
        cfg.request_form_email = (form.request_form_email.data or '').strip().lower() or None
        cfg.request_form_first_message = (form.request_form_first_message.data or '').strip() or None
        # Nudge settings
        try:
            cfg.nudge_enabled = True if form.nudge_enable.data == 'true' else False
        except Exception:
            cfg.nudge_enabled = False
        try:
            cfg.nudge_interval_hours = int(form.nudge_interval_hours.data) if form.nudge_interval_hours.data else 24
        except Exception:
            cfg.nudge_interval_hours = 24

        # If an SSO user was selected, store the user id (0 means none)
        try:
            cfg.help_user_id = int(form.help_user.data) if form.help_user.data else None
        except Exception:
            cfg.help_user_id = None
        try:
            cfg.request_form_user_id = int(form.request_form_user.data) if form.request_form_user.data else None
        except Exception:
            cfg.request_form_user_id = None

        # Runtime integration toggles
        try:
            cfg.email_override = bool(form.email_toggle.data)
        except Exception:
            cfg.email_override = False
        try:
            cfg.ticketing_override = bool(form.ticketing_toggle.data)
        except Exception:
            cfg.ticketing_override = False
        try:
            cfg.inventory_override = bool(form.inventory_toggle.data)
        except Exception:
            cfg.inventory_override = False

        db.session.commit()
        flash('Special email settings saved.', 'success')
        return redirect(url_for('admin.special_emails'))

    # Prefill on GET
    if flask_request.method == 'GET':
        form.enable_feature.data = 'true' if cfg.enabled else 'false'
        form.help_email.data = cfg.help_email or ''
        form.request_form_email.data = cfg.request_form_email or ''
        form.request_form_first_message.data = cfg.request_form_first_message or ''
        form.help_user.data = cfg.help_user_id or 0
        form.request_form_user.data = cfg.request_form_user_id or 0
        form.nudge_enable.data = 'true' if cfg.nudge_enabled else 'false'
        form.nudge_interval_hours.data = cfg.nudge_interval_hours or 24

    return render_template('admin_special_emails.html', form=form, cfg=cfg)


@admin_bp.route('/forms')
@login_required
def form_templates():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    templates = FormTemplate.query.order_by(FormTemplate.created_at.desc()).all()
    return render_template('admin_form_templates.html', templates=templates)


@admin_bp.route('/forms/new', methods=['GET', 'POST'])
@login_required
def form_new():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    form = FormTemplateForm()
    if form.validate_on_submit():
        t = FormTemplate(name=form.name.data.strip(), description=form.description.data.strip() if form.description.data else None)
        db.session.add(t)
        db.session.commit()
        flash('Template created.', 'success')
        return redirect(url_for('admin.form_templates'))
    return render_template('admin_form_edit.html', form=form)


@admin_bp.route('/forms/<int:template_id>/edit', methods=['GET', 'POST'])
@login_required
def form_edit(template_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    t = FormTemplate.query.get_or_404(template_id)
    form = FormTemplateForm(obj=t)
    if form.validate_on_submit():
        t.name = form.name.data.strip()
        t.description = form.description.data.strip() if form.description.data else None
        db.session.commit()
        flash('Template updated.', 'success')
        return redirect(url_for('admin.form_templates'))
    fields = t.fields.order_by(FormField.order.asc()).all()
    return render_template('admin_form_edit.html', form=form, template=t, fields=fields)


@admin_bp.route('/forms/<int:template_id>/fields/new', methods=['GET', 'POST'])
@login_required
def form_field_new(template_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    t = FormTemplate.query.get_or_404(template_id)
    form = FormFieldForm()
    if form.validate_on_submit():
        f = FormField(
            template_id=t.id,
            name=form.name.data.strip(),
            label=form.label.data.strip(),
            field_type=form.field_type.data,
            required=bool(form.required.data),
            hint=form.hint.data.strip() if form.hint.data else None,
            order=int(form.order.data or 0),
            verification=json.loads(form.verification_json.data) if form.verification_json.data else None,
        )
        db.session.add(f)
        db.session.commit()
        # options
        if form.options_csv.data:
            for idx, val in enumerate([v.strip() for v in form.options_csv.data.split(',') if v.strip()]):
                opt = FormFieldOption(field_id=f.id, value=val, label=val, order=idx)
                db.session.add(opt)
            db.session.commit()
        flash('Field added.', 'success')
        return redirect(url_for('admin.form_edit', template_id=t.id))
    return render_template('admin_form_field_new.html', form=form, template=t)


@admin_bp.route('/forms/<int:template_id>/assign', methods=['GET', 'POST'])
@login_required
def form_assign(template_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    t = FormTemplate.query.get_or_404(template_id)
    form = DepartmentAssignmentForm()
    if form.validate_on_submit():
        a = DepartmentFormAssignment(template_id=t.id, department_id=form.department_id.data or None, department_name=form.department_name.data or None)
        db.session.add(a)
        db.session.commit()
        flash('Assigned template to department.', 'success')
        return redirect(url_for('admin.form_templates'))
    return render_template('admin_form_assign.html', form=form, template=t)


@admin_bp.post('/forms/<int:template_id>/delete')
@login_required
def form_delete(template_id: int):
    if not _is_admin_user():
        return jsonify({'ok': False, 'error': 'access_denied'}), 403
    t = FormTemplate.query.get_or_404(template_id)
    try:
        db.session.delete(t)
        db.session.commit()
        return jsonify({'ok': True, 'deleted': template_id})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'failed'})



@admin_bp.route('/buckets')
@login_required
def buckets_list():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    from ..models import StatusBucket
    buckets = StatusBucket.query.order_by(StatusBucket.order.asc(), StatusBucket.created_at.desc()).all()
    return render_template('admin_buckets.html', buckets=buckets)


@admin_bp.route('/buckets/new', methods=['GET', 'POST'])
@login_required
def buckets_new():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    form = BucketForm()
    if form.validate_on_submit():
        from ..models import StatusBucket
        b = StatusBucket(name=form.name.data.strip(), department_id=form.department_id.data or None, department_name=form.department_name.data or None, order=int(form.order.data or 0), active=bool(form.active.data))
        db.session.add(b)
        db.session.commit()
        flash('Bucket created.', 'success')
        return redirect(url_for('admin.buckets_list'))
    return render_template('admin_bucket_edit.html', form=form)


@admin_bp.post('/buckets/import_default')
@login_required
def buckets_import_default():
    """Create a recommended 6-bucket layout for quick setup.

    Idempotent: will not duplicate buckets of the same name for the same department.
    """
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    from ..models import StatusBucket, BucketStatus

    # Recommended layout (for Dept B by default)
    dept_name = 'B'
    layout = [
        ('New', ['NEW_FROM_A']),
        ('In Progress', ['B_IN_PROGRESS', 'PENDING_C_REVIEW', 'B_FINAL_REVIEW']),
        ('Needs Input', ['WAITING_ON_A_RESPONSE', 'C_NEEDS_CHANGES']),
        ('Pending Approval', ['EXEC_APPROVAL', 'C_APPROVED', 'SENT_TO_A']),
        ('Completed', ['CLOSED']),
        ('Archived', []),
    ]

    created = 0
    for idx, (name, statuses) in enumerate(layout):
        exists = StatusBucket.query.filter_by(name=name, department_name=dept_name).first()
        if exists:
            # update statuses: remove existing and recreate to match recommended
            for s in exists.statuses.all():
                db.session.delete(s)
            for sidx, code in enumerate(statuses):
                db.session.add(BucketStatus(bucket_id=exists.id, status_code=code, order=sidx))
            db.session.commit()
            continue

        b = StatusBucket(name=name, department_name=dept_name, order=idx, active=True)
        db.session.add(b)
        db.session.commit()
        for sidx, code in enumerate(statuses):
            db.session.add(BucketStatus(bucket_id=b.id, status_code=code, order=sidx))
        db.session.commit()
        created += 1

    flash(f'Imported recommended buckets (created {created} new).', 'success')
    return redirect(url_for('admin.buckets_list'))


@admin_bp.route('/buckets/<int:bucket_id>/edit', methods=['GET', 'POST'])
@login_required
def buckets_edit(bucket_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    from ..models import StatusBucket, BucketStatus
    b = StatusBucket.query.get_or_404(bucket_id)
    form = BucketForm(obj=b)
    if form.validate_on_submit():
        b.name = form.name.data.strip()
        b.department_id = form.department_id.data or None
        b.department_name = form.department_name.data or None
        b.order = int(form.order.data or 0)
        b.active = bool(form.active.data)
        db.session.commit()
        flash('Bucket updated.', 'success')
        return redirect(url_for('admin.buckets_list'))
    statuses = b.statuses.order_by(BucketStatus.order.asc()).all()
    return render_template('admin_bucket_edit.html', form=form, bucket=b, statuses=statuses)


@admin_bp.route('/buckets/<int:bucket_id>/statuses/new', methods=['GET', 'POST'])
@login_required
def bucket_status_new(bucket_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    from ..models import StatusBucket, BucketStatus
    b = StatusBucket.query.get_or_404(bucket_id)
    form = BucketStatusForm()
    if form.validate_on_submit():
        bs = BucketStatus(bucket_id=b.id, status_code=form.status_code.data.strip(), order=int(form.order.data or 0))
        db.session.add(bs)
        db.session.commit()
        flash('Status added to bucket.', 'success')
        return redirect(url_for('admin.buckets_edit', bucket_id=b.id))
    return render_template('admin_bucket_status_new.html', form=form, bucket=b)


@admin_bp.post('/buckets/<int:bucket_id>/delete')
@login_required
def buckets_delete(bucket_id: int):
    if not _is_admin_user():
        return jsonify({'ok': False, 'error': 'access_denied'}), 403
    from ..models import StatusBucket
    b = StatusBucket.query.get_or_404(bucket_id)
    try:
        db.session.delete(b)
        db.session.commit()
        return jsonify({'ok': True, 'deleted': bucket_id})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'failed'})


@admin_bp.post('/buckets/<int:bucket_id>/statuses/<int:status_id>/delete')
@login_required
def bucket_status_delete(bucket_id: int, status_id: int):
    if not _is_admin_user():
        return jsonify({'ok': False, 'error': 'access_denied'}), 403
    from ..models import BucketStatus
    s = BucketStatus.query.get_or_404(status_id)
    try:
        db.session.delete(s)
        db.session.commit()
        return jsonify({'ok': True, 'deleted': status_id})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'failed'})


@admin_bp.route('/departments')
@login_required
def departments_list():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    deps = Department.query.order_by(Department.order.asc(), Department.created_at.desc()).all()
    return render_template('admin_departments.html', departments=deps)


@admin_bp.route('/departments/new', methods=['GET', 'POST'])
@login_required
def departments_new():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    form = DepartmentFormAdmin()
    if form.validate_on_submit():
        d = Department(code=form.code.data.strip().upper(), name=form.name.data.strip(), order=int(form.order.data or 0), active=bool(form.active.data))
        db.session.add(d)
        db.session.commit()
        flash('Department created.', 'success')
        return redirect(url_for('admin.departments_list'))
    return render_template('admin_department_edit.html', form=form)


@admin_bp.route('/departments/<int:dept_id>/edit', methods=['GET', 'POST'])
@login_required
def departments_edit(dept_id: int):
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    d = Department.query.get_or_404(dept_id)
    form = DepartmentFormAdmin(obj=d)
    if form.validate_on_submit():
        d.code = form.code.data.strip().upper()
        d.name = form.name.data.strip()
        d.order = int(form.order.data or 0)
        d.active = bool(form.active.data)
        db.session.commit()
        flash('Department updated.', 'success')
        return redirect(url_for('admin.departments_list'))
    return render_template('admin_department_edit.html', form=form, department=d)


@admin_bp.post('/departments/<int:dept_id>/delete')
@login_required
def departments_delete(dept_id: int):
    if not _is_admin_user():
        return jsonify({'ok': False, 'error': 'access_denied'}), 403
    d = Department.query.get_or_404(dept_id)
    try:
        db.session.delete(d)
        db.session.commit()
        return jsonify({'ok': True, 'deleted': dept_id})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'failed'})


@admin_bp.route('/site_config', methods=['GET', 'POST'])
@login_required
def site_config():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))
    cfg = SiteConfig.get()
    form = SiteConfigForm()
    if form.validate_on_submit():
        cfg.banner_html = form.banner_html.data or None
        cfg.rolling_quotes_enabled = bool(form.rolling_enabled.data)
        lines = [l.strip() for l in (form.rolling_csv.data or '').splitlines() if l.strip()]
        cfg.rolling_quotes = lines
        db.session.add(cfg)
        db.session.commit()
        flash('Site configuration saved.', 'success')
        return redirect(url_for('admin.site_config'))
    # prefill
    if request.method == 'GET':
        form.banner_html.data = cfg.banner_html or ''
        form.rolling_enabled.data = bool(cfg.rolling_quotes_enabled)
        form.rolling_csv.data = '\n'.join(cfg.rolling_quotes or [])
    return render_template('admin_site_config.html', form=form, cfg=cfg)


@admin_bp.route('/themes', methods=['GET', 'POST'])
@login_required
def themes():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    from .forms import ThemeForm
    form = ThemeForm()
    themes = AppTheme.query.order_by(AppTheme.created_at.desc()).all()

    if form.validate_on_submit():
        # handle uploads
        logo_filename = None
        upload = flask_request.files.get('logo_upload')
        if upload and upload.filename:
            from werkzeug.utils import secure_filename
            import time, uuid
            fn = secure_filename(upload.filename)
            # prefix with timestamp+uuid to avoid collisions
            base, ext = os.path.splitext(fn)
            fn_ts = f"{int(time.time())}-{uuid.uuid4().hex}{ext}"
            try:
                static_upload_dir = os.path.join(current_app.static_folder or 'static', 'uploads')
                os.makedirs(static_upload_dir, exist_ok=True)
                dest = os.path.join(static_upload_dir, fn_ts)
                upload.save(dest)
                # store path relative to static so url_for('static', filename=...) works
                logo_filename = os.path.join('uploads', fn_ts)
            except Exception:
                current_app.logger.exception('Failed to save uploaded logo')

        # prefer explicit URL if provided
        logo_url = form.logo_url.data.strip() if form.logo_url.data else None

        # If a logo URL was provided, prefer that (store as external URL in logo_filename)
        stored_logo = logo_filename or (logo_url if logo_url else None)

        t = AppTheme(name=form.name.data.strip(), css=form.css.data or None, logo_filename=stored_logo)
        db.session.add(t)
        if form.active.data:
            # deactivate others
            AppTheme.query.update({'active': False})
            t.active = True

        db.session.commit()
        flash('Theme saved.', 'success')
        return redirect(url_for('admin.themes'))

    return render_template('admin_themes.html', form=form, themes=themes)


@admin_bp.post('/themes/<int:theme_id>/activate')
@login_required
def themes_activate(theme_id: int):
    if not _is_admin_user():
        return jsonify({'ok': False, 'error': 'access_denied'}), 403
    t = AppTheme.query.get_or_404(theme_id)
    try:
        AppTheme.query.update({'active': False})
        t.active = True
        db.session.commit()
        return jsonify({'ok': True, 'theme_id': t.id})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'failed'})


@admin_bp.post('/themes/<int:theme_id>/delete')
@login_required
def themes_delete(theme_id: int):
    if not _is_admin_user():
        return jsonify({'ok': False, 'error': 'access_denied'}), 403
    t = AppTheme.query.get_or_404(theme_id)
    try:
        db.session.delete(t)
        db.session.commit()
        return jsonify({'ok': True, 'deleted': theme_id})
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'failed'})


@admin_bp.route('/special_emails/trigger', methods=['POST'])
@login_required
def trigger_autoresponder():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    sender = flask_request.form.get('sender') or flask_request.args.get('sender')
    if not sender:
        flash('Provide sender email via `sender` parameter.', 'warning')
        return redirect(url_for('admin.special_emails'))

    ok = notifications.send_request_form_autoresponder(sender)
    if ok:
        flash(f'Autoresponder queued to {sender}.', 'success')
    else:
        flash('Autoresponder not sent (feature disabled or misconfigured).', 'warning')
    return redirect(url_for('admin.special_emails'))
