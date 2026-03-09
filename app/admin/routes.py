from flask import Blueprint, render_template, redirect, url_for, flash, current_app, session
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import User, UserDepartmentMembership, ProcessFlowGroup, ProcessFlowStep, ProcessStatus
from .forms import AdminCreateUserForm, FlowGroupForm, FlowStepForm, ProcessStatusForm
from ..models import Request as ReqModel, Artifact, Submission
from datetime import datetime, timedelta
from flask import request as flask_request
from ..models import Notification, AuditLog
from urllib.parse import unquote

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

KNOWN_STATUSES = [
    "NEW_FROM_A",
    "B_IN_PROGRESS",
    "WAITING_ON_A_RESPONSE",
    "PENDING_C_REVIEW",
    "C_APPROVED",
    "C_NEEDS_CHANGES",
    "B_FINAL_REVIEW",
    "EXEC_APPROVAL",
    "SENT_TO_A",
    "CLOSED",
]


def _status_options() -> list:
    configured = [s.code for s in ProcessStatus.query.order_by(ProcessStatus.code.asc()).all()]
    ordered = []
    for code in KNOWN_STATUSES + configured:
        if code not in ordered:
            ordered.append(code)
    return ordered


def _is_admin_user():
    # Basic admin check
    if not (current_user.is_authenticated and getattr(current_user, "is_admin", False)):
        return False

    # If SSO is enabled and admin access requires MFA, enforce it.
    if current_app.config.get("SSO_ENABLED") and current_app.config.get("SSO_REQUIRE_MFA"):
        # SSO login flow should set `session['sso_mfa'] = True` when MFA was verified.
        return bool(session.get("sso_mfa", False))

    return True


def _set_default_group(group: ProcessFlowGroup) -> None:
    """Ensure there is only one default group."""
    ProcessFlowGroup.query.filter(ProcessFlowGroup.id != group.id).update({"is_default": False})
    group.is_default = True


def _normalize_departments(values) -> list[str]:
    out = []
    for raw in values or []:
        dept = (raw or "").upper().strip()
        if dept in ("A", "B", "C") and dept not in out:
            out.append(dept)
    return out


def _sync_user_department_memberships(user: User, departments) -> None:
    """Sync auxiliary department memberships and keep primary department included."""
    wanted = set(_normalize_departments(departments))
    wanted.add((user.department or "A").upper())

    existing = {m.department: m for m in user.department_memberships}
    for dept, row in list(existing.items()):
        if dept not in wanted:
            db.session.delete(row)

    for dept in wanted:
        if dept not in existing:
            db.session.add(UserDepartmentMembership(user_id=user.id, department=dept))


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
            _sync_user_department_memberships(existing, form.department_memberships.data)
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
        db.session.flush()
        _sync_user_department_memberships(u, form.department_memberships.data)
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
    if flask_request.method == "GET":
        form.department_memberships.data = list(u.member_departments())
    # don't prefill password
    form.password.data = None

    if form.validate_on_submit():
        u.email = form.email.data.strip().lower()
        u.name = form.name.data.strip() if form.name.data else None
        u.department = form.department.data
        if form.password.data:
            u.password_hash = generate_password_hash(form.password.data, method="pbkdf2:sha256")
        u.is_active = bool(form.is_active.data)
        _sync_user_department_memberships(u, form.department_memberships.data)
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


@admin_bp.route("/statuses")
@login_required
def list_statuses():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    statuses = ProcessStatus.query.order_by(ProcessStatus.code.asc()).all()
    return render_template("admin_statuses.html", statuses=statuses)


@admin_bp.route("/statuses/new", methods=["GET", "POST"])
@login_required
def create_status():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = ProcessStatusForm()
    if form.validate_on_submit():
        behavior = form.behavior.data
        transfer_to_department = (form.transfer_to_department.data or "").strip() or None
        if behavior == "transfer" and not transfer_to_department:
            flash("Transfer behavior requires a target department.", "danger")
            return render_template("admin_status_form.html", form=form, edit=None)

        code = (form.code.data or "").strip().upper()
        if ProcessStatus.query.filter_by(code=code).first():
            flash(f"Status code {code} already exists.", "danger")
            return render_template("admin_status_form.html", form=form, edit=None)

        status = ProcessStatus(
            code=code,
            label=(form.label.data or "").strip(),
            description=(form.description.data or "").strip() or None,
            behavior=behavior,
            transfer_to_department=transfer_to_department,
            is_active=bool(form.is_active.data),
        )
        db.session.add(status)
        db.session.commit()
        flash("Status created.", "success")
        return redirect(url_for("admin.list_statuses"))

    return render_template("admin_status_form.html", form=form, edit=None)


@admin_bp.route("/statuses/<int:status_id>/edit", methods=["GET", "POST"])
@login_required
def edit_status(status_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    status = ProcessStatus.query.get_or_404(status_id)
    form = ProcessStatusForm(obj=status)
    if form.validate_on_submit():
        behavior = form.behavior.data
        transfer_to_department = (form.transfer_to_department.data or "").strip() or None
        if behavior == "transfer" and not transfer_to_department:
            flash("Transfer behavior requires a target department.", "danger")
            return render_template("admin_status_form.html", form=form, edit=status)

        code = (form.code.data or "").strip().upper()
        dup = ProcessStatus.query.filter(ProcessStatus.code == code, ProcessStatus.id != status.id).first()
        if dup:
            flash(f"Status code {code} already exists.", "danger")
            return render_template("admin_status_form.html", form=form, edit=status)

        status.code = code
        status.label = (form.label.data or "").strip()
        status.description = (form.description.data or "").strip() or None
        status.behavior = behavior
        status.transfer_to_department = transfer_to_department
        status.is_active = bool(form.is_active.data)
        db.session.commit()
        flash("Status updated.", "success")
        return redirect(url_for("admin.list_statuses"))

    return render_template("admin_status_form.html", form=form, edit=status)


@admin_bp.route("/statuses/<int:status_id>/delete", methods=["POST"])
@login_required
def delete_status(status_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    status = ProcessStatus.query.get_or_404(status_id)
    in_requests = ReqModel.query.filter_by(status=status.code).first() is not None
    in_steps = ProcessFlowStep.query.filter(
        (ProcessFlowStep.from_status == status.code) | (ProcessFlowStep.to_status == status.code)
    ).first() is not None
    if in_requests or in_steps:
        flash("Status is in use and cannot be deleted; set it inactive instead.", "warning")
        return redirect(url_for("admin.list_statuses"))

    db.session.delete(status)
    db.session.commit()
    flash("Status deleted.", "success")
    return redirect(url_for("admin.list_statuses"))


@admin_bp.route("/flows")
@login_required
def list_flows():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    groups = ProcessFlowGroup.query.order_by(ProcessFlowGroup.name.asc()).all()
    return render_template("admin_flows.html", groups=groups)


@admin_bp.route("/flows/<int:group_id>")
@login_required
def flow_group_detail(group_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    group = ProcessFlowGroup.query.get_or_404(group_id)
    focus_dept = (flask_request.args.get("dept") or "").upper()
    if focus_dept not in ("A", "B", "C"):
        focus_dept = None

    steps = group.steps
    if focus_dept:
        steps = [s for s in steps if s.actor_department == focus_dept]

    return render_template(
        "admin_flow_group_detail.html",
        group=group,
        steps=steps,
        focus_dept=focus_dept,
    )


@admin_bp.route("/flows/new", methods=["GET", "POST"])
@login_required
def create_flow_group():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = FlowGroupForm()
    if form.validate_on_submit():
        group = ProcessFlowGroup(
            name=(form.name.data or "").strip(),
            description=(form.description.data or "").strip() or None,
            is_active=bool(form.is_active.data),
            is_default=bool(form.is_default.data),
        )
        db.session.add(group)
        db.session.flush()
        if group.is_default:
            _set_default_group(group)
        db.session.commit()
        flash("Flow group created.", "success")
        return redirect(url_for("admin.list_flows"))

    return render_template("admin_flow_group_form.html", form=form, edit=None)


@admin_bp.route("/flows/<int:group_id>/edit", methods=["GET", "POST"])
@login_required
def edit_flow_group(group_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    group = ProcessFlowGroup.query.get_or_404(group_id)
    form = FlowGroupForm(obj=group)
    if form.validate_on_submit():
        group.name = (form.name.data or "").strip()
        group.description = (form.description.data or "").strip() or None
        group.is_active = bool(form.is_active.data)
        group.is_default = bool(form.is_default.data)
        if group.is_default:
            _set_default_group(group)
        db.session.commit()
        flash("Flow group updated.", "success")
        return redirect(url_for("admin.list_flows"))

    return render_template("admin_flow_group_form.html", form=form, edit=group)


@admin_bp.route("/flows/<int:group_id>/default", methods=["POST"])
@login_required
def make_flow_group_default(group_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    group = ProcessFlowGroup.query.get_or_404(group_id)
    if not group.is_active:
        flash("Only active flow groups can be set as default.", "warning")
        return redirect(url_for("admin.list_flows"))

    _set_default_group(group)
    db.session.commit()
    flash(f"{group.name} is now the default flow group.", "success")
    return redirect(url_for("admin.list_flows"))


@admin_bp.route("/flows/<int:group_id>/delete", methods=["POST"])
@login_required
def delete_flow_group(group_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    group = ProcessFlowGroup.query.get_or_404(group_id)
    if group.is_default:
        flash("Default flow group cannot be deleted until another default is selected.", "warning")
        return redirect(url_for("admin.list_flows"))

    db.session.delete(group)
    db.session.commit()
    flash("Flow group deleted.", "success")
    return redirect(url_for("admin.list_flows"))


@admin_bp.route("/flows/<int:group_id>/steps/new", methods=["GET", "POST"])
@login_required
def create_flow_step(group_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    group = ProcessFlowGroup.query.get_or_404(group_id)
    form = FlowStepForm()
    preset_dept = (flask_request.args.get("dept") or "").upper()
    if flask_request.method == "GET" and preset_dept in ("A", "B", "C"):
        form.actor_department.data = preset_dept
    if form.validate_on_submit():
        step = ProcessFlowStep(
            flow_group_id=group.id,
            name=(form.name.data or "").strip() or None,
            sort_order=form.sort_order.data,
            actor_department=form.actor_department.data,
            from_status=(form.from_status.data or "").strip(),
            to_status=(form.to_status.data or "").strip(),
            from_department=(form.from_department.data or "").strip() or None,
            to_department=(form.to_department.data or "").strip() or None,
            requires_submission=bool(form.requires_submission.data),
        )
        db.session.add(step)
        db.session.commit()
        flash("Flow step created.", "success")
        return redirect(url_for("admin.flow_group_detail", group_id=group.id, dept=step.actor_department))

    return render_template("admin_flow_step_form.html", form=form, group=group, status_options=_status_options(), edit=None)


@admin_bp.route("/flows/steps/<int:step_id>/edit", methods=["GET", "POST"])
@login_required
def edit_flow_step(step_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    step = ProcessFlowStep.query.get_or_404(step_id)
    form = FlowStepForm(obj=step)
    if form.validate_on_submit():
        step.name = (form.name.data or "").strip() or None
        step.sort_order = form.sort_order.data
        step.actor_department = form.actor_department.data
        step.from_status = (form.from_status.data or "").strip()
        step.to_status = (form.to_status.data or "").strip()
        step.from_department = (form.from_department.data or "").strip() or None
        step.to_department = (form.to_department.data or "").strip() or None
        step.requires_submission = bool(form.requires_submission.data)
        db.session.commit()
        flash("Flow step updated.", "success")
        return redirect(url_for("admin.flow_group_detail", group_id=step.flow_group_id, dept=step.actor_department))

    return render_template("admin_flow_step_form.html", form=form, group=step.flow_group, status_options=_status_options(), edit=step)


@admin_bp.route("/flows/steps/<int:step_id>/delete", methods=["POST"])
@login_required
def delete_flow_step(step_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    step = ProcessFlowStep.query.get_or_404(step_id)
    group_id = step.flow_group_id
    actor_dept = step.actor_department
    db.session.delete(step)
    db.session.commit()
    flash("Flow step deleted.", "success")
    return redirect(url_for("admin.flow_group_detail", group_id=group_id, dept=actor_dept))



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
