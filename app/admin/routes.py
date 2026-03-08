from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    current_app,
    session,
    jsonify,
)
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
from ..models import (
    Notification,
    AuditLog,
    NotificationRetention,
    StatusBucket,
    BucketStatus,
)
from ..models import FeatureFlags, RejectRequestConfig
from urllib.parse import unquote
import os
import json
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
from .forms import GuestFormAdminForm
from ..models import GuestForm
from ..requests_bp.workflow import owner_for_status
from ..services.integrations import (
    INTEGRATION_KIND_SCAFFOLDS,
    get_integration_scaffold,
    integration_config_summary,
    normalize_integration_config,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _normalize_department_code(value):
    raw = (value or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper in {"A", "B", "C"}:
        return upper
    compact = upper.replace("DEPARTMENT", "").replace("DEPT", "").strip()
    return compact if compact in {"A", "B", "C"} else ""


def _default_workflow_spec():
    steps = [
        {"from_dept": "A", "to_dept": "B", "status": "NEW_FROM_A"},
        {"from_dept": "B", "to_dept": "B", "status": "B_IN_PROGRESS"},
        {"from_dept": "B", "to_dept": "C", "status": "PENDING_C_REVIEW"},
        {"from_dept": "C", "to_dept": "B", "status": "B_FINAL_REVIEW"},
        {"from_dept": "B", "to_dept": "A", "status": "SENT_TO_A"},
        {"from_dept": "A", "to_dept": "B", "status": "CLOSED"},
    ]
    transitions = []
    for i in range(len(steps) - 1):
        transitions.append(
            {
                "from": steps[i]["status"],
                "to": steps[i + 1]["status"],
                "from_status": steps[i]["status"],
                "to_status": steps[i + 1]["status"],
                "from_dept": steps[i].get("to_dept") or steps[i].get("from_dept"),
                "to_dept": steps[i + 1].get("to_dept") or steps[i + 1].get("from_dept"),
            }
        )
    return {"steps": steps, "transitions": transitions}


def _normalize_workflow_spec(spec, workflow_name=None):
    if not isinstance(spec, dict):
        return spec

    steps = spec.get("steps") or []
    if not steps:
        return spec
    if any(
        isinstance(step, dict) and (step.get("from_dept") or step.get("to_dept"))
        for step in steps
    ):
        return spec

    statuses = [str(step).strip() for step in steps if isinstance(step, str) and step.strip()]
    if not statuses:
        return spec

    default_statuses = [step["status"] for step in _default_workflow_spec()["steps"]]
    if statuses == default_statuses:
        normalized = dict(spec)
        normalized.update(_default_workflow_spec())
        return normalized

    rich_steps = []
    prev_status = None
    prev_to_dept = None
    for status in statuses:
        to_dept = _normalize_department_code(owner_for_status(status)) or prev_to_dept or "B"
        if prev_status is None:
            from_dept = "A" if status == "NEW_FROM_A" else to_dept
        else:
            from_dept = prev_to_dept or _normalize_department_code(owner_for_status(prev_status)) or to_dept
        rich_steps.append(
            {"from_dept": from_dept, "to_dept": to_dept, "status": status}
        )
        prev_status = status
        prev_to_dept = to_dept

    transitions = []
    for i in range(len(rich_steps) - 1):
        transitions.append(
            {
                "from": rich_steps[i]["status"],
                "to": rich_steps[i + 1]["status"],
                "from_status": rich_steps[i]["status"],
                "to_status": rich_steps[i + 1]["status"],
                "from_dept": rich_steps[i].get("to_dept") or rich_steps[i].get("from_dept"),
                "to_dept": rich_steps[i + 1].get("to_dept") or rich_steps[i + 1].get("from_dept"),
            }
        )

    normalized = dict(spec)
    normalized["steps"] = rich_steps
    normalized["transitions"] = transitions
    return normalized


def _build_status_options_map(workflow=None):
    status_options_map = {"A": set(), "B": set(), "C": set()}

    try:
        for bs in BucketStatus.query.all():
            dept = _normalize_department_code(
                (bs.bucket.department_name or "") if bs.bucket else ""
            )
            if dept:
                status_options_map.setdefault(dept, set()).add(bs.status_code)
    except Exception:
        pass

    try:
        for opt in StatusOption.query.order_by(StatusOption.code.asc()).all():
            dept = _normalize_department_code(opt.target_department) or _normalize_department_code(owner_for_status(opt.code))
            if dept:
                status_options_map.setdefault(dept, set()).add(opt.code)
    except Exception:
        pass

    try:
        workflows = [workflow] if workflow is not None else Workflow.query.all()
        for wf in workflows:
            normalized = _normalize_workflow_spec(
                getattr(wf, "spec", None), getattr(wf, "name", None)
            ) or {}
            for step in normalized.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                code = (step.get("status") or step.get("code") or "").strip()
                depts = {
                    _normalize_department_code(step.get("from_dept")),
                    _normalize_department_code(step.get("to_dept")),
                    _normalize_department_code(step.get("department")),
                    _normalize_department_code(step.get("department_code")),
                }
                for dept in {d for d in depts if d}:
                    if code:
                        status_options_map.setdefault(dept, set()).add(code)
    except Exception:
        pass

    return {dept: sorted(values) for dept, values in status_options_map.items() if values}


def _workflow_scope_label(workflow):
    explicit = (getattr(workflow, "department_code", None) or "").strip()
    if explicit:
        return explicit

    spec = getattr(workflow, "spec", None) or {}
    steps = spec.get("steps") if isinstance(spec, dict) else []
    departments = []
    seen = set()

    for step in steps or []:
        if not isinstance(step, dict):
            continue
        for key in ("from_dept", "to_dept", "department", "department_code"):
            value = (step.get(key) or "").strip() if isinstance(step.get(key), str) else ""
            if value and value not in seen:
                seen.add(value)
                departments.append(value)

    if departments:
        return " / ".join(departments)

    name = (getattr(workflow, "name", None) or "").upper()
    inferred = [dept for dept in ("A", "B", "C") if dept in name]
    if inferred:
        return " / ".join(inferred)

    return "Global"


def _is_admin_user():
    # Basic admin check
    if not (current_user.is_authenticated and getattr(current_user, "is_admin", False)):
        return False

    # If SSO is enabled and admin access requires MFA, enforce it.
    if current_app.config.get("SSO_ENABLED") and current_app.config.get(
        "SSO_REQUIRE_MFA"
    ):
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
        is_admin = (getattr(form, "role", None) and form.role.data == "admin") or bool(
            form.is_admin.data
        )

        existing = User.query.filter_by(email=email).first()
        if existing:
            existing.name = name or existing.name
            existing.department = dept
            if form.password.data:
                existing.password_hash = generate_password_hash(
                    pw, method="pbkdf2:sha256"
                )
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
            u.password_hash = generate_password_hash(
                form.password.data, method="pbkdf2:sha256"
            )
        u.is_active = bool(form.is_active.data)
        u.is_admin = (
            getattr(form, "role", None) and form.role.data == "admin"
        ) or bool(form.is_admin.data)
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


@admin_bp.route("/users/<int:user_id>/departments", methods=["GET", "POST"])
@login_required
def manage_user_departments(user_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    u = get_or_404(User, user_id)
    # Supported department codes (keep in sync with models/choices)
    choices = ["A", "B", "C"]

    if flask_request.method == "POST":
        selected = flask_request.form.getlist("departments") or []
        selected = [s.strip().upper() for s in selected if s and s.strip()]

        # Remove existing assignments not in selected
        existing = {ud.department: ud for ud in getattr(u, "departments", [])}
        for dept_code, ud in list(existing.items()):
            if dept_code not in selected:
                try:
                    db.session.delete(ud)
                except Exception:
                    db.session.rollback()

        # Add any new assignments
        for dept in selected:
            if dept == getattr(u, "department", None):
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
            flash("Updated department assignments.", "success")
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            flash("Failed to save assignments.", "danger")

        return redirect(url_for("admin.list_users"))

    # GET: show current assignments
    assigned = [ud.department for ud in getattr(u, "departments", [])]
    return render_template(
        "admin_user_departments.html", user=u, choices=choices, assigned=assigned
    )


@admin_bp.route("/users/<int:user_id>/impersonate", methods=["POST"])
@login_required
def impersonate_user(user_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    if current_user.id == user_id:
        flash("Cannot impersonate yourself.", "warning")
        return redirect(url_for("admin.list_users"))

    target = get_or_404(User, user_id)
    if not target.is_active:
        flash("Cannot impersonate an inactive user.", "warning")
        return redirect(url_for("admin.list_users"))
    # record admin id and the department to impersonate
    session["impersonate_admin_id"] = current_user.id
    session["impersonate_dept"] = target.department
    session["impersonate_started_at"] = datetime.utcnow().isoformat()

    # add an audit entry (system-level; request_id left null)
    entry = AuditLog(
        request_id=None,
        actor_type="user",
        actor_user_id=current_user.id,
        actor_label=current_user.email,
        action_type="impersonation_start",
        note=f"Started impersonation as department {target.department}",
        event_ts=datetime.utcnow(),
    )
    db.session.add(entry)
    db.session.commit()

    flash(
        f"Now acting as a member of Dept {target.department} (you remain {current_user.email}).",
        "info",
    )
    return redirect(url_for("requests.dashboard"))


@admin_bp.route("/impersonate/dept", methods=["POST"])
@login_required
def impersonate_dept():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    dept = flask_request.form.get("dept") or flask_request.args.get("dept")
    if not dept or dept.upper() not in ("A", "B", "C"):
        flash("Invalid department selected.", "warning")
        return redirect(url_for("admin.list_users"))
    dept = dept.upper()

    session["impersonate_admin_id"] = current_user.id
    session["impersonate_dept"] = dept
    session["impersonate_started_at"] = datetime.utcnow().isoformat()

    entry = AuditLog(
        request_id=None,
        actor_type="user",
        actor_user_id=current_user.id,
        actor_label=current_user.email,
        action_type="impersonation_start",
        note=f"Started impersonation as department {dept}",
    )
    db.session.add(entry)
    db.session.commit()

    flash(
        f"Now acting as a member of Dept {dept} (you remain {current_user.email}).",
        "info",
    )
    return redirect(url_for("requests.dashboard"))


@admin_bp.route("/impersonate/stop", methods=["POST"])
@login_required
def stop_impersonation():
    admin_id = session.get("impersonate_admin_id")
    if not admin_id:
        flash("Not currently impersonating.", "warning")
        return redirect(url_for("requests.dashboard"))

    # record stop audit
    entry = AuditLog(
        request_id=None,
        actor_type="user",
        actor_user_id=current_user.id,
        actor_label=current_user.email,
        action_type="impersonation_stop",
        note=f"Stopped impersonation; admin {current_user.email} restored their session",
        event_ts=datetime.utcnow(),
    )
    db.session.add(entry)
    db.session.commit()

    # clear impersonation flags
    session.pop("impersonate_admin_id", None)
    session.pop("impersonate_dept", None)
    session.pop("impersonate_started_at", None)
    flash("Stopped acting-as; returned to your normal admin session.", "success")
    return redirect(url_for("admin.list_users"))


@admin_bp.route("/set_self_admin", methods=["POST"])
@login_required
def set_self_admin():
    """Allow a logged-in user to mark their account as admin when enabled via config.

    This action is gated by the `ALLOW_SELF_ADMIN` config flag to avoid accidental
    elevation in production environments.
    """
    if not current_app.config.get("ALLOW_SELF_ADMIN"):
        flash("Self-admin feature is not enabled on this instance.", "danger")
        return redirect(flask_request.referrer or url_for("requests.dashboard"))

    # mark the current user as admin
    current_user.is_admin = True
    try:
        db.session.commit()
        flash("Your account has been updated to admin.", "success")
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash("Failed to update admin status.", "danger")

    return redirect(flask_request.referrer or url_for("admin.index"))


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
    recent_email_issues = (
        Notification.query.filter(
            Notification.type.in_(["email_failed", "email_skipped"])
        )
        .order_by(Notification.created_at.desc())
        .limit(20)
        .all()
    )

    if dept == "A":
        # Show requests created by users in Dept A (monitoring view)
        reqs = (
            ReqModel.query.join(User, ReqModel.created_by_user_id == User.id)
            .filter(User.department == "A")
            .order_by(ReqModel.updated_at.desc())
            .all()
        )
        dashboard_html = render_template(
            "dashboard.html", mode="A", requests=reqs, now=now
        )
        return render_template(
            "admin_monitor.html",
            dept=dept,
            dashboard_html=dashboard_html,
            total_users=total_users,
            active_users=active_users,
            admin_count=admin_count,
            recent_email_issues=recent_email_issues,
        )

    if dept == "B":
        # Build buckets similar to Dept B dashboard but for monitoring.
        # Use department-scoped queries so monitoring honors handoffs as well.
        from ..utils.dept_scope import scope_requests_for_department

        base_b = scope_requests_for_department(ReqModel.query, "B")
        buckets = {
            "New from A": base_b.filter(ReqModel.status == "NEW_FROM_A")
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "In progress by Department B": base_b.filter(
                ReqModel.status == "B_IN_PROGRESS"
            )
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "Pending review from Department A": base_b.filter(
                ReqModel.status == "WAITING_ON_A_RESPONSE"
            )
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "Needs changes": base_b.filter(ReqModel.status == "C_NEEDS_CHANGES")
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "Exec approval required": base_b.filter(ReqModel.status == "EXEC_APPROVAL")
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "Approved by C": base_b.filter(ReqModel.status == "C_APPROVED")
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "Final review": base_b.filter(ReqModel.status == "B_FINAL_REVIEW")
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "Sent to A": base_b.filter(ReqModel.status == "SENT_TO_A")
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "Under review by Department C": base_b.filter(
                ReqModel.status == "PENDING_C_REVIEW"
            )
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "Closed": base_b.filter(ReqModel.status == "CLOSED")
            .order_by(ReqModel.updated_at.desc())
            .all(),
            "All (B)": base_b.order_by(ReqModel.updated_at.desc()).all(),
        }

        status_codes = [
            "B_IN_PROGRESS",
            "WAITING_ON_A_RESPONSE",
            "PENDING_C_REVIEW",
            "EXEC_APPROVAL",
            "B_FINAL_REVIEW",
            "SENT_TO_A",
            "CLOSED",
        ]
        status_counts = {
            code: base_b.filter(ReqModel.status == code).count()
            for code in status_codes
        }

        dashboard_html = render_template(
            "dashboard.html",
            mode="B",
            buckets=buckets,
            status_counts=status_counts,
            now=now,
        )
        return render_template(
            "admin_monitor.html",
            dept=dept,
            dashboard_html=dashboard_html,
            total_users=total_users,
            active_users=active_users,
            admin_count=admin_count,
            recent_email_issues=recent_email_issues,
        )

    if dept == "C":
        pending = (
            ReqModel.query.filter_by(status="PENDING_C_REVIEW")
            .order_by(ReqModel.updated_at.desc())
            .all()
        )
        dashboard_html = render_template(
            "dashboard.html", mode="C", requests=pending, now=now
        )
        return render_template(
            "admin_monitor.html",
            dept=dept,
            dashboard_html=dashboard_html,
            total_users=total_users,
            active_users=active_users,
            admin_count=admin_count,
            recent_email_issues=recent_email_issues,
        )

    flash("Unknown department", "warning")
    return redirect(url_for("admin.monitor", dept="B"))


@admin_bp.route("/guest_forms")
@login_required
def list_guest_forms():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    forms = GuestForm.query.order_by(GuestForm.created_at.desc()).all()
    return render_template("admin_guest_forms.html", forms=forms)


@admin_bp.route("/guest_forms/new", methods=["GET", "POST"])
@login_required
def create_guest_form():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    templates = FormTemplate.query.order_by(FormTemplate.name.asc()).all()
    choices = [(0, "-- none --")] + [(t.id, t.name) for t in templates]
    form = GuestFormAdminForm()
    form.template_id.choices = choices

    if form.validate_on_submit():
        slug = form.slug.data.strip()
        g = GuestForm(
            name=form.name.data.strip(),
            slug=slug,
            template_id=(form.template_id.data or None) or None,
            require_sso=bool(form.require_sso.data),
            owner_department=form.owner_department.data or "B",
            is_default=bool(form.is_default.data),
            active=bool(form.active.data),
        )
        if g.is_default:
            # unset other defaults
            try:
                GuestForm.query.update({GuestForm.is_default: False})
                db.session.flush()
            except Exception:
                db.session.rollback()
        db.session.add(g)
        try:
            db.session.commit()
            flash("Guest form created.", "success")
            return redirect(url_for("admin.list_guest_forms"))
        except Exception:
            db.session.rollback()
            flash("Failed to create guest form.", "danger")

    return render_template("admin_guest_form_edit.html", form=form)


@admin_bp.route("/guest_forms/<int:gf_id>/edit", methods=["GET", "POST"])
@login_required
def edit_guest_form(gf_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    g = get_or_404(GuestForm, gf_id)
    templates = FormTemplate.query.order_by(FormTemplate.name.asc()).all()
    choices = [(0, "-- none --")] + [(t.id, t.name) for t in templates]
    form = GuestFormAdminForm(obj=g)
    form.template_id.choices = choices
    form.template_id.data = g.template_id or 0
    form.owner_department.data = g.owner_department or "B"

    if form.validate_on_submit():
        g.name = form.name.data.strip()
        g.slug = form.slug.data.strip()
        g.template_id = (form.template_id.data or None) or None
        g.require_sso = bool(form.require_sso.data)
        g.owner_department = form.owner_department.data or "B"
        g.active = bool(form.active.data)
        if form.is_default.data:
            try:
                GuestForm.query.update({GuestForm.is_default: False})
                db.session.flush()
            except Exception:
                db.session.rollback()
            g.is_default = True
        else:
            g.is_default = False
        try:
            db.session.commit()
            flash("Guest form updated.", "success")
            return redirect(url_for("admin.list_guest_forms"))
        except Exception:
            db.session.rollback()
            flash("Failed to update guest form.", "danger")

    return render_template("admin_guest_form_edit.html", form=form, edit=g)


@admin_bp.route("/guest_forms/<int:gf_id>/delete", methods=["POST"])
@login_required
def delete_guest_form(gf_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    g = get_or_404(GuestForm, gf_id)
    try:
        db.session.delete(g)
        db.session.commit()
        flash("Guest form deleted.", "success")
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash("Failed to delete guest form.", "danger")
    return redirect(url_for("admin.list_guest_forms"))


@admin_bp.route("/")
@login_required
def index():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    total_users = User.query.count()
    total_depts = Department.query.count()
    total_audit = AuditLog.query.count()
    return render_template(
        "admin_index.html",
        total_users=total_users,
        total_depts=total_depts,
        total_audit=total_audit,
    )


@admin_bp.route("/debug_workspace")
@login_required
def debug_workspace():
    # Small helper page that loads an internal path inside an iframe for debugging.
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    path = (
        flask_request.args.get("path") or flask_request.args.get("url") or "/dashboard"
    )
    # Basic safety: allow only internal paths starting with '/'
    try:
        path = unquote(path)
    except Exception:
        pass
    if not path.startswith("/"):
        path = "/dashboard"
    return render_template("admin_debug_workspace.html", path=path)


@admin_bp.route("/debug/cleanup", methods=["POST"])
@login_required
def debug_cleanup():
    # Admin-only maintenance endpoint to remove smoke or debug rows.
    if not _is_admin_user():
        return jsonify({"error": "access_denied"}), 403

    confirm = flask_request.args.get("confirm") or flask_request.form.get("confirm")
    if str(confirm).lower() != "true":
        return jsonify({"error": "missing_confirm", "note": "set confirm=true"}), 400

    try:
        days = int(flask_request.args.get("days") or 0)
    except Exception:
        days = 0

    if days > 0:
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = ReqModel.query.filter(
            ReqModel.is_debug == True, ReqModel.created_at < cutoff
        ).delete(synchronize_session=False)
    else:
        deleted = ReqModel.query.filter(ReqModel.title.like("SMOKE_%")).delete(
            synchronize_session=False
        )

    db.session.commit()
    return jsonify({"deleted": int(deleted)})


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
        audits = audits.join(User, AuditLog.actor_user_id == User.id).filter(
            User.email.ilike(f"%{q}%")
        )
    if action:
        audits = audits.filter(AuditLog.action_type.ilike(f"%{action}%"))
    audits = audits.limit(200).all()
    return render_template("admin_audit.html", audits=audits)


@admin_bp.route("/assign_sso", methods=["GET", "POST"])
@login_required
def assign_sso():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = SSOAssignForm()
    if form.validate_on_submit():
        raw = form.emails.data or ""
        emails = [e.strip().lower() for e in raw.splitlines() if e.strip()]
        return redirect(url_for("admin.list_users"))
        dept = form.department.data
        updated = []
        skipped = []
        for em in emails:
            u = User.query.filter_by(email=em).first()
            if not u:
                skipped.append((em, "not_found"))
                continue
            if not u.sso_sub:
                skipped.append((em, "no_sso"))
                continue
            u.department = dept
            u.is_active = True
            updated.append(em)
        if updated:
            db.session.commit()
        flash(f"Assigned {len(updated)} users to Dept {dept}.", "success")
        if skipped:
            flash("Skipped: " + ", ".join([f"{e}({r})" for e, r in skipped]), "warning")
        return redirect(url_for("admin.list_users"))

    return render_template("admin_assign_sso.html", form=form)


@admin_bp.route("/bulk_assign_departments", methods=["GET", "POST"])
@login_required
def bulk_assign_departments():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = BulkDepartmentAssignForm()
    if form.validate_on_submit():
        dept = (form.department.data or "").strip().upper()
        raw = form.emails.data or ""
        # Accept newline or comma separated
        parts = []
        for line in raw.splitlines():
            for token in line.split(","):
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
                report_errors.append({"email": em, "error": str(exc)})
                continue
            if not u:
                report_missing.append(em)
                continue

            if getattr(u, "department", None) == dept:
                report_skipped_primary.append(em)
                continue

            existing = UserDepartment.query.filter_by(
                user_id=u.id, department=dept
            ).first()
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
                report_errors.append({"email": em, "error": str(exc)})

        return render_template(
            "admin_bulk_assign_report.html",
            dept=dept,
            assigned=report_assigned,
            missing=report_missing,
            skipped_primary=report_skipped_primary,
            skipped_existing=report_skipped_existing,
            errors=report_errors,
        )

    return render_template("admin_bulk_assign_departments.html", form=form)


@admin_bp.route("/site_config", methods=["GET", "POST"])
@login_required
def site_config():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # `SiteConfig.get` has its own defensive error handling; prefer it here so
    # that a misconfigured or out‑of‑date database won't blow up the admin UI.
    try:
        cfg = SiteConfig.get()
    except Exception as exc:  # pragma: no cover - extremely rare but safe
        current_app.logger.exception("unable to load site config")
        flash(
            "Unable to load site configuration (database error). "
            "Please ensure migrations have been applied.",
            "danger",
        )
        # fall back to empty object so form rendering still works
        cfg = None
    else:
        # SiteConfig.get will return a fresh object if the query failed due to a
        # missing table/column.  That object will not have been committed and
        # therefore its primary key will still be ``None``.  This is worth
        # warning the admin about so they know something's wrong in the
        # database even though the page will render.
        if cfg is not None and getattr(cfg, "id", None) is None:
            flash(
                "Site configuration cannot be loaded from the database; "
                "your schema may be out of date.",
                "warning",
            )

    form = SiteConfigForm(obj=cfg)
    if flask_request.method == "GET" and cfg:
        form.brand_name.data = getattr(cfg, "brand_name", None)
        form.theme_preset.data = getattr(cfg, "theme_preset", "default") or "default"
        form.navbar_banner.data = getattr(cfg, "banner_html", None) or getattr(
            cfg, "navbar_banner", None
        )
        try:
            rq = getattr(cfg, "rolling_quotes", []) or []
            form.rolling_quotes.data = (
                "\n".join(rq) if isinstance(rq, list) else str(rq)
            )
        except Exception:
            form.rolling_quotes.data = None
        try:
            # expose named quote-sets to the admin UI (JSON map)
            sets = getattr(cfg, "rolling_quote_sets", {}) or {}
            form.rolling_quote_sets.data = json.dumps(sets, indent=2)
        except Exception:
            form.rolling_quote_sets.data = None
        try:
            # populate choices for active set selector
            keys = list((getattr(cfg, "rolling_quote_sets", {}) or {}).keys())
            if not keys:
                keys = list(cfg.rolling_quote_sets.keys()) if cfg else ['default']
            if 'default' not in keys:
                keys.insert(0, 'default')
            form.active_quote_set.choices = [(k, k.title()) for k in keys]
            form.active_quote_set.data = getattr(cfg, 'active_quote_set', 'default')
        except Exception:
            form.active_quote_set.choices = [('default','Default')]
            form.active_quote_set.data = getattr(cfg, 'active_quote_set', 'default')
        form.show_banner.data = bool(
            getattr(cfg, "rolling_quotes_enabled", getattr(cfg, "show_banner", False))
        )

    if form.validate_on_submit():
        if not cfg:
            cfg = SiteConfig()
            db.session.add(cfg)
        # Support both current field names and legacy payload keys used by tests/UI.
        banner = form.navbar_banner.data
        if not banner:
            banner = flask_request.form.get("banner_html")

        rolling_enabled = bool(form.show_banner.data)
        if "rolling_enabled" in flask_request.form:
            rolling_enabled = True

        rolling_input = form.rolling_quotes.data
        if not rolling_input:
            rolling_input = flask_request.form.get("rolling_csv")

        cfg.brand_name = (form.brand_name.data or "").strip() or None
        cfg.theme_preset = (form.theme_preset.data or "default").strip().lower()
        if cfg.theme_preset not in ("default", "ocean", "forest", "sunset", "midnight"):
            cfg.theme_preset = "default"

        remove_logo = bool(form.clear_logo.data)
        uploaded_logo = flask_request.files.get("logo_upload")
        if remove_logo:
            cfg.logo_filename = None
        if uploaded_logo and uploaded_logo.filename:
            filename = secure_filename(uploaded_logo.filename)
            if filename:
                ext = os.path.splitext(filename)[1].lower()
                stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
                stored_name = f"logo_{stamp}{ext}"
                rel_dir = os.path.join("uploads", "branding")
                static_dir = current_app.static_folder or os.path.join(
                    current_app.root_path, "static"
                )
                abs_dir = os.path.join(static_dir, rel_dir)
                os.makedirs(abs_dir, exist_ok=True)
                uploaded_logo.save(os.path.join(abs_dir, stored_name))
                cfg.logo_filename = f"uploads/branding/{stored_name}"

        cfg.banner_html = _sanitize_banner_html(banner) or None
        cfg.rolling_quotes_enabled = rolling_enabled
        cfg.rolling_quotes = rolling_input or None
        # save named quote sets if provided (expect JSON map string)
        try:
            if form.rolling_quote_sets.data:
                parsed = json.loads(form.rolling_quote_sets.data)
                if isinstance(parsed, dict):
                    cfg._rolling_quote_sets = json.dumps(parsed)
                else:
                    cfg._rolling_quote_sets = None
            else:
                cfg._rolling_quote_sets = None
        except Exception:
            cfg._rolling_quote_sets = None
        try:
            cfg.active_quote_set = form.active_quote_set.data or 'default'
        except Exception:
            cfg.active_quote_set = 'default'
        try:
            db.session.commit()
            flash("Site configuration saved.", "success")
        except Exception as exc:  # pragma: no cover - defensive
            current_app.logger.exception("failed to save site config")
            try:
                db.session.rollback()
            except Exception:
                pass
            flash(
                "Failed to save site configuration (database error).", "danger"
            )
        return redirect(url_for("admin.site_config"))

    return render_template("admin_site_config.html", form=form, cfg=cfg)


@admin_bp.route("/quotes", methods=["GET"])
@login_required
def quotes_config():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    return redirect(url_for("admin.site_config", _anchor="quotes-settings"))


@admin_bp.route("/site_config/preview", methods=["POST"])
@login_required
def site_config_preview():
    if not _is_admin_user():
        return jsonify({"error": "access_denied"}), 403

    # Accept multipart form or JSON payload
    raw_sets = None
    raw_quotes = None
    try:
        raw_sets = flask_request.form.get("rolling_quote_sets") or flask_request.json and flask_request.json.get("rolling_quote_sets")
        raw_quotes = flask_request.form.get("rolling_csv") or flask_request.form.get("rolling_quotes") or (flask_request.json and flask_request.json.get("rolling_quotes"))
    except Exception:
        raw_sets = None
        raw_quotes = None

    active = flask_request.form.get("active_quote_set") or (flask_request.json and flask_request.json.get("active_quote_set")) or "default"

    try:
        parsed = json.loads(raw_sets) if raw_sets else {}
    except Exception:
        return jsonify({"error": "invalid_json", "message": "Could not parse rolling_quote_sets as JSON."}), 400

    if not isinstance(parsed, dict):
        return jsonify({"error": "invalid_type", "message": "rolling_quote_sets must be a JSON object."}), 400

    if raw_quotes:
        parsed.setdefault(
            "default",
            [line.strip() for line in str(raw_quotes).splitlines() if line.strip()],
        )

    active_list = parsed.get(active) or parsed.get(str(active)) or []
    if not isinstance(active_list, list):
        return jsonify({"error": "invalid_set", "message": "Active set is not a list."}), 400

    sample = [s for s in active_list if isinstance(s, str)][:20]
    return jsonify({"active": active, "count": len(active_list), "sample": sample})


def _sanitize_banner_html(raw: str) -> str:
    """Sanitize admin-provided banner HTML for safe display.

    This function performs light cleaning to remove markdown code fences
    (```...```) and stray triple-backticks that sometimes get pasted into
    the banner content. We deliberately avoid heavy HTML sanitization here
    because banner content is expected to be HTML; this helper focuses on
    removing accidental code fences and obvious artifacts that break the
    navbar rendering.
    """
    if not raw:
        return raw

    # first remove accidental fenced-code artifacts which often break the
    # navbar rendering (e.g. ```...```) so we strip those explicitly.
    import re

    s = str(raw or "")
    s = re.sub(r"```[\s\S]*?```", "", s)
    s = s.replace('```', '')

    # Use bleach to perform a conservative HTML sanitization: allow a small
    # set of formatting tags and safe attributes, strip anything else (including
    # <script> tags and event handlers). We avoid allowing inline CSS here to
    # keep banner rendering predictable.
    try:
        import bleach

        allowed_tags = [
            "a",
            "b",
            "strong",
            "i",
            "em",
            "u",
            "p",
            "br",
            "span",
            "div",
            "ul",
            "ol",
            "li",
            "img",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "small",
            "blockquote",
            "pre",
            "code",
            "hr",
        ]

        allowed_attrs = {
            "a": ["href", "title", "target", "rel"],
            "img": ["src", "alt", "title", "width", "height"],
            "*": ["id", "class", "role", "aria-hidden"],
        }

        # Tight CSS whitelist: only permit a short, safe set of CSS properties
        # for inline `style` usage. This prevents arbitrary CSS from affecting
        # layout or injecting harmful rules.
        try:
            from bleach.css_sanitizer import CSSSanitizer

            css_whitelist = [
                "color",
                "background-color",
                "text-align",
                "font-weight",
                "font-style",
                "text-decoration",
                "vertical-align",
            ]
            css_sanitizer = CSSSanitizer(allowed_css_properties=css_whitelist)
            allowed_attrs["*"] = allowed_attrs["*"] + ["style"]
        except Exception:
            css_sanitizer = None

        cleaned = bleach.clean(
            s,
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=["http", "https", "mailto"],
            strip=True,
            css_sanitizer=css_sanitizer,
        )
        # Remove navigation/file targets that point at static assets so banner
        # markup cannot hijack button clicks or navigate users to JS/CSS files.
        cleaned = re.sub(
            r'\s(?:href|src|action|formaction)=(["\'])/static/[^"\']*\1',
            '',
            cleaned,
            flags=re.IGNORECASE,
        )
        # Trim and return
        return (cleaned or "").strip()
    except Exception:
        # If bleach isn't available for some reason, fall back to the lighter
        # regex-based cleanup we used previously (best-effort).
        return s.strip()


@admin_bp.route('/site_config/clean_banner', methods=['POST'])
@login_required
def clean_banner():
    if not _is_admin_user():
        flash('Access denied.', 'danger')
        return redirect(url_for('requests.dashboard'))

    cfg = SiteConfig.query.first()
    if not cfg or not getattr(cfg, 'banner_html', None):
        flash('No banner content found to clean.', 'info')
        return redirect(url_for('admin.site_config'))

    cleaned = _sanitize_banner_html(cfg.banner_html or '')
    if cleaned == (cfg.banner_html or ''):
        flash('Banner content appears clean (no changes made).', 'info')
        return redirect(url_for('admin.site_config'))

    try:
        cfg.banner_html = cleaned or None
        db.session.commit()
        flash('Banner content cleaned successfully.', 'success')
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash('Failed to save cleaned banner content.', 'danger')

    return redirect(url_for('admin.site_config'))


@admin_bp.route('/site_config/preview_banner', methods=['POST'])
@login_required
def preview_banner():
    """Return a JSON preview of original vs cleaned banner HTML.

    This endpoint allows the admin UI to show a side-by-side preview before
    committing changes.
    """
    if not _is_admin_user():
        return jsonify({'error': 'access_denied'}), 403

    raw = flask_request.form.get('banner') or flask_request.form.get('navbar_banner') or ''
    cleaned = _sanitize_banner_html(raw)
    return jsonify({'original': raw, 'cleaned': cleaned})


@admin_bp.route("/workflows")
@login_required
def list_workflows():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    wfs = Workflow.query.order_by(Workflow.name.asc()).all()
    workflow_scope_labels = {wf.id: _workflow_scope_label(wf) for wf in wfs}
    return render_template(
        "admin_workflows.html",
        workflows=wfs,
        workflow_scope_labels=workflow_scope_labels,
    )


@admin_bp.route("/workflows/new", methods=["GET", "POST"])
@login_required
def create_workflow():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    form = WorkflowForm()
    if form.validate_on_submit():
        wf = Workflow(
            name=form.name.data.strip(),
            description=(form.description.data or "").strip() or None,
            department_code=(form.department_code.data or None) or None,
            spec=None,
            active=bool(form.active.data),
        )
        # attempt to parse JSON if provided, otherwise accept steps[] fallback
        import json

        if form.spec_json.data:
            try:
                wf.spec = json.loads(form.spec_json.data)
            except Exception:
                flash("Invalid JSON for workflow spec.", "danger")
                return render_template("admin_workflow_form.html", form=form)
        else:
            steps = flask_request.form.getlist("steps[]") or flask_request.form.getlist(
                "steps"
            )
            if steps:
                steps = [s.strip() for s in steps if s and s.strip()]
                transitions = []
                for i in range(len(steps) - 1):
                    transitions.append({"from": steps[i], "to": steps[i + 1]})
                wf.spec = {"steps": steps, "transitions": transitions}
        db.session.add(wf)
        db.session.commit()
        action = flask_request.form.get('action') or 'save'
        # If admin chose to implement, create any missing StatusOption rows
        if action == 'implement':
            try:
                from ..models import StatusOption

                steps = []
                if isinstance(wf.spec, dict):
                    steps = wf.spec.get('steps') or []
                for s in steps:
                    code = None
                    target_dept = None
                    if isinstance(s, str):
                        code = s
                    elif isinstance(s, dict):
                        code = s.get('status') or s.get('code')
                        target_dept = s.get('to_dept') or s.get('to')
                    if not code:
                        continue
                    existing = StatusOption.query.filter_by(code=code).first()
                    if not existing:
                        label = code.replace('_', ' ').title()
                        opt = StatusOption(code=code, label=label)
                        if target_dept:
                            opt.target_department = target_dept or None
                        db.session.add(opt)
                db.session.commit()
                flash('Workflow created and status options implemented.', 'success')
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                flash('Workflow created but failed to implement status options.', 'warning')
            return redirect(url_for('admin.list_workflows'))
        flash("Workflow created.", "success")
        return redirect(url_for("admin.list_workflows"))
    return render_template(
        "admin_workflow_form.html",
        form=form,
        status_options_map=_build_status_options_map(),
    )


@admin_bp.route("/workflows/<int:wf_id>/edit", methods=["GET", "POST"])
@login_required
def edit_workflow(wf_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    wf = get_or_404(Workflow, wf_id)
    form = WorkflowForm(obj=wf)
    # prefill spec_json
    if flask_request.method == "GET" and wf.spec is not None:
        import json

        try:
            form.spec_json.data = json.dumps(
                _normalize_workflow_spec(wf.spec, wf.name), indent=2
            )
        except Exception:
            form.spec_json.data = str(wf.spec)

    if form.validate_on_submit():
        wf.name = form.name.data.strip()
        wf.description = (form.description.data or "").strip() or None
        wf.department_code = (form.department_code.data or None) or None
        wf.active = bool(form.active.data)
        if form.spec_json.data:
            import json

            try:
                wf.spec = json.loads(form.spec_json.data)
            except Exception:
                flash("Invalid JSON for workflow spec.", "danger")
                return render_template("admin_workflow_form.html", form=form, wf=wf)
        else:
            steps = flask_request.form.getlist("steps[]") or flask_request.form.getlist(
                "steps"
            )
            if steps:
                steps = [s.strip() for s in steps if s and s.strip()]
                transitions = []
                for i in range(len(steps) - 1):
                    transitions.append({"from": steps[i], "to": steps[i + 1]})
                wf.spec = {"steps": steps, "transitions": transitions}
            else:
                wf.spec = None
        db.session.commit()
        action = flask_request.form.get('action') or 'save'
        if action == 'implement':
            try:
                from ..models import StatusOption

                steps = []
                if isinstance(wf.spec, dict):
                    steps = wf.spec.get('steps') or []
                for s in steps:
                    code = None
                    target_dept = None
                    if isinstance(s, str):
                        code = s
                    elif isinstance(s, dict):
                        code = s.get('status') or s.get('code')
                        target_dept = s.get('to_dept') or s.get('to')
                    if not code:
                        continue
                    existing = StatusOption.query.filter_by(code=code).first()
                    if not existing:
                        label = code.replace('_', ' ').title()
                        opt = StatusOption(code=code, label=label)
                        if target_dept:
                            opt.target_department = target_dept or None
                        db.session.add(opt)
                db.session.commit()
                flash('Workflow updated and status options implemented.', 'success')
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                flash('Workflow updated but failed to implement status options.', 'warning')
            return redirect(url_for('admin.list_workflows'))
        flash("Workflow updated.", "success")
        return redirect(url_for("admin.list_workflows"))
    return render_template(
        "admin_workflow_form.html",
        form=form,
        wf=wf,
        editor_spec=_normalize_workflow_spec(wf.spec, wf.name),
        status_options_map=_build_status_options_map(wf),
    )


@admin_bp.route("/workflows/<int:wf_id>/delete", methods=["POST"])
@login_required
def delete_workflow(wf_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    wf = get_or_404(Workflow, wf_id)
    db.session.delete(wf)
    db.session.commit()
    flash("Workflow deleted.", "success")
    return redirect(url_for("admin.list_workflows"))


@admin_bp.route("/workflows/<int:wf_id>/toggle", methods=["POST"])
@login_required
def toggle_workflow_active(wf_id: int):
    if not _is_admin_user():
        return jsonify({"error": "access_denied"}), 403
    wf = get_or_404(Workflow, wf_id)
    try:
        wf.active = not bool(wf.active)
        db.session.commit()
        return jsonify({"ok": True, "active": bool(wf.active)})
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"ok": False}), 500


@admin_bp.route("/unmapped-submissions")
@login_required
def unmapped_submissions():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # Load recent submissions and filter for those without an automated mapping
    subs = Submission.query.order_by(Submission.created_at.desc()).limit(200).all()
    unmapped = []
    for s in subs:
        data = getattr(s, "data", None) or {}
        if not (isinstance(data, dict) and data.get("_mapped")):
            unmapped.append(s)

    return render_template("admin_unmapped_submissions.html", submissions=unmapped)


@admin_bp.route(
    "/unmapped-submissions/<int:submission_id>/map", methods=["GET", "POST"]
)
@login_required
def map_submission(submission_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    s = get_or_404(Submission, submission_id)
    data = getattr(s, "data", {}) or {}
    # present only payload keys that look like user fields (skip internal metadata)
    payload_keys = [
        k
        for k in (list(data.keys()) if isinstance(data, dict) else [])
        if not str(k).startswith("_")
    ]

    # Fields available in the template (if any)
    template = None
    fields = []
    try:
        if s.template_id:
            template = FormTemplate.query.get(s.template_id)
        if template:
            fields = sorted(
                getattr(template, "fields", []) or [], key=lambda f: f.label
            )
    except Exception:
        current_app.logger.exception("Failed loading template/fields for mapping UI")

    if flask_request.method == "POST":
        # Expect form keys map__<payload_key> -> field_id or empty
        mapping = {}
        for pk in payload_keys:
            form_key = f"map__{pk}"
            val = flask_request.form.get(form_key)
            if val:
                try:
                    fid = int(val)
                    mapping[pk] = fid
                except Exception:
                    continue

        # Persist mapping into the submission.data under reserved keys
        try:
            newdata = dict(data or {})
            field_map = {}
            for pk, fid in mapping.items():
                # capture the value and the mapped field id
                field_map[str(fid)] = {"payload_key": pk, "value": newdata.get(pk)}
            if field_map:
                newdata["_field_map"] = field_map
                newdata["_mapped"] = True
                s.data = newdata
                db.session.commit()
                flash("Saved mapping for submission.", "success")
                return redirect(url_for("admin.unmapped_submissions"))
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            current_app.logger.exception("Failed saving mapping for submission")
            flash("Failed saving mapping.", "danger")

    return render_template(
        "admin_map_submission.html",
        submission=s,
        payload_keys=payload_keys,
        fields=fields,
    )


@admin_bp.route("/templates")
@login_required
def list_templates():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    templates = FormTemplate.query.order_by(FormTemplate.created_at.desc()).all()
    return render_template("admin_templates.html", templates=templates)


@admin_bp.route("/templates/new", methods=["GET", "POST"])
@login_required
def create_template():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    form = FormTemplateAdminForm()
    if form.validate_on_submit():
        t = FormTemplate(
            name=form.name.data.strip(),
            description=(form.description.data or "").strip() or None,
            external_enabled=bool(
                getattr(form, "external_enabled", None) and form.external_enabled.data
            ),
            external_provider=(
                getattr(form, "external_provider", None)
                and (form.external_provider.data or "").strip()
            )
            or None,
            external_form_url=(
                getattr(form, "external_form_url", None)
                and (form.external_form_url.data or "").strip()
            )
            or None,
            external_form_id=(
                getattr(form, "external_form_id", None)
                and (form.external_form_id.data or "").strip()
            )
            or None,
        )
        db.session.add(t)
        db.session.commit()
        # create requested number of empty fields
        try:
            n = int(form.field_count.data or 0)
        except Exception:
            n = 0
        for i in range(max(0, n)):
            f = FormField(
                template_id=t.id,
                name=f"field_{i+1}",
                label=f"Field {i+1}",
                field_type="text",
                required=False,
            )
            db.session.add(f)
        db.session.commit()
        flash("Template created. Edit fields as needed.", "success")
        return redirect(url_for("admin.edit_template_fields", template_id=t.id))
    return render_template("admin_template_form.html", form=form)


@admin_bp.route("/templates/<int:template_id>/fields", methods=["GET", "POST"])
@login_required
def edit_template_fields(template_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    t = get_or_404(FormTemplate, template_id)
    # Handle simple bulk update: inputs named field_<id>_label, field_<id>_required
    if flask_request.method == "POST":
        for f in t.fields:
            lab = flask_request.form.get(f"field_{f.id}_label")
            nm = flask_request.form.get(f"field_{f.id}_name")
            req = flask_request.form.get(f"field_{f.id}_required")
            ft = flask_request.form.get(f"field_{f.id}_type")
            if lab is not None:
                f.label = lab.strip()
            if nm is not None:
                f.name = nm.strip() or f.name
            if ft is not None:
                f.field_type = ft
            f.required = bool(req)
            db.session.add(f)
        # save external integration settings if present
        try:
            # checkbox present means 'on' or '1'
            ext_enabled = flask_request.form.get("external_enabled")
            t.external_enabled = bool(ext_enabled)
            t.external_provider = (
                flask_request.form.get("external_provider") or ""
            ).strip() or None
            t.external_form_url = (
                flask_request.form.get("external_form_url") or ""
            ).strip() or None
            t.external_form_id = (
                flask_request.form.get("external_form_id") or ""
            ).strip() or None
            db.session.add(t)
        except Exception:
            pass
        db.session.commit()
        flash("Fields updated.", "success")
        return redirect(url_for("admin.list_templates"))

    # Render editing UI
    fields = sorted(
        list(t.fields), key=lambda ff: getattr(ff, "created_at", getattr(ff, "id", 0))
    )
    return render_template("admin_edit_template_fields.html", template=t, fields=fields)


@admin_bp.route("/fields/<int:field_id>/verification", methods=["GET", "POST"])
@login_required
def edit_field_verification(field_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    f = get_or_404(FormField, field_id)
    # pick latest mapping if multiple
    fv = (
        FieldVerification.query.filter_by(field_id=f.id)
        .order_by(FieldVerification.created_at.desc())
        .first()
    )
    form = FieldVerificationForm()
    if flask_request.method == "GET" and fv:
        form.provider.data = fv.provider
        form.external_key.data = fv.external_key
        import json

        try:
            form.params_json.data = (
                json.dumps(fv.params, indent=2) if fv.params is not None else ""
            )
        except Exception:
            form.params_json.data = str(fv.params or "")
        try:
            form.triggers_auto_reject.data = bool(
                getattr(fv, "triggers_auto_reject", False)
            )
        except Exception:
            form.triggers_auto_reject.data = False
        try:
            params = fv.params if isinstance(fv.params, dict) else {}
        except Exception:
            params = {}
        form.verify_each_separated_value.data = bool(
            params.get("verify_each_separated_value", False)
        )
        form.value_separator.data = str(
            params.get("value_separator") or params.get("separator") or ","
        )
        form.bulk_input_hint.data = (
            params.get("bulk_input_hint") or params.get("entry_hint") or ""
        )

    if form.validate_on_submit():
        import json

        params = {}
        if form.params_json.data:
            try:
                params = json.loads(form.params_json.data)
            except Exception:
                flash("Invalid JSON in params field.", "danger")
                return render_template(
                    "admin_field_verification.html", form=form, field=f, fv=fv
                )
            if not isinstance(params, dict):
                flash("Params JSON must be a JSON object.", "danger")
                return render_template(
                    "admin_field_verification.html", form=form, field=f, fv=fv
                )

        params["verify_each_separated_value"] = bool(
            form.verify_each_separated_value.data
        )
        params["value_separator"] = (
            (form.value_separator.data or "").strip() or ","
        )
        if (form.bulk_input_hint.data or "").strip():
            params["bulk_input_hint"] = form.bulk_input_hint.data.strip()
        else:
            params.pop("bulk_input_hint", None)

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
        flash("Field verification mapping saved.", "success")
        return redirect(
            url_for("admin.edit_template_fields", template_id=f.template_id)
        )

    return render_template("admin_field_verification.html", form=form, field=f, fv=fv)


@admin_bp.route("/notifications_retention", methods=["GET", "POST"])
@login_required
def notifications_retention():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    cfg = NotificationRetention.get()
    form = NotificationRetentionForm()
    if flask_request.method == "GET":
        # prefill form
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
        flash("Notification retention updated.", "success")
        return redirect(url_for("admin.notifications_retention"))

    return render_template("admin_notifications_retention.html", form=form, cfg=cfg)


@admin_bp.route("/special_email", methods=["GET", "POST"])
@login_required
def special_email():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

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
        sso_users = (
            User.query.filter(User.sso_sub.isnot(None)).order_by(User.email.asc()).all()
        )
    except Exception:
        current_app.logger.exception(
            "Failed querying SSO users for special_email admin page"
        )
        try:
            db.session.rollback()
        except Exception:
            pass
        sso_users = []

    form.request_form_user_id.choices = [(0, "-- None --")] + [
        (u.id, f"{u.email} (Dept {u.department})") for u in sso_users
    ]
    if flask_request.method == "GET" and cfg:
        form.enabled.data = bool(getattr(cfg, "enabled", False))
        form.request_form_email.data = getattr(cfg, "request_form_email", None)
        form.request_form_user_id.data = int(
            getattr(cfg, "request_form_user_id", 0) or 0
        )
        form.request_form_first_message.data = getattr(
            cfg, "request_form_first_message", None
        )
        form.request_form_department.data = (
            getattr(cfg, "request_form_department", "A") or "A"
        )
        form.request_form_field_validation_enabled.data = bool(
            getattr(cfg, "request_form_field_validation_enabled", False)
        )
        form.request_form_auto_reject_oos_enabled.data = bool(
            getattr(cfg, "request_form_auto_reject_oos_enabled", False)
        )
        form.request_form_inventory_out_of_stock_notify_enabled.data = bool(
            getattr(cfg, "request_form_inventory_out_of_stock_notify_enabled", False)
        )
        form.request_form_inventory_out_of_stock_notify_mode.data = (
            getattr(cfg, "request_form_inventory_out_of_stock_notify_mode", "email")
            or "email"
        )
        form.request_form_inventory_out_of_stock_message.data = getattr(
            cfg, "request_form_inventory_out_of_stock_message", None
        )
        form.nudge_enabled.data = bool(getattr(cfg, "nudge_enabled", False))
        # convert stored float to string for the select field
        form.nudge_interval_hours.data = str(
            float(getattr(cfg, "nudge_interval_hours", 24) or 24)
        )
        form.nudge_min_delay_hours.data = int(
            getattr(cfg, "nudge_min_delay_hours", 4) or 4
        )

    if form.validate_on_submit():
        if not cfg:
            from ..models import SpecialEmailConfig

            cfg = SpecialEmailConfig()
            db.session.add(cfg)

        cfg.enabled = bool(form.enabled.data)
        selected_owner_id = int(form.request_form_user_id.data or 0)
        selected_owner = (
            db.session.get(User, selected_owner_id) if selected_owner_id else None
        )
        if selected_owner and not selected_owner.sso_sub:
            selected_owner = None
            selected_owner_id = 0

        cfg.request_form_user_id = selected_owner_id or None
        manual_inbox = (form.request_form_email.data or "").strip() or None
        cfg.request_form_email = manual_inbox or (
            selected_owner.email if selected_owner else None
        )
        cfg.request_form_first_message = (
            form.request_form_first_message.data or ""
        ).strip() or None
        cfg.request_form_department = (
            (form.request_form_department.data or "A").strip().upper()
        )
        if selected_owner:
            cfg.request_form_department = (
                (selected_owner.department or cfg.request_form_department or "A")
                .strip()
                .upper()
            )
        if cfg.request_form_department not in ("A", "B", "C"):
            cfg.request_form_department = "A"
        cfg.request_form_field_validation_enabled = bool(
            form.request_form_field_validation_enabled.data
        )
        cfg.request_form_auto_reject_oos_enabled = bool(
            form.request_form_auto_reject_oos_enabled.data
        )
        cfg.request_form_inventory_out_of_stock_notify_enabled = bool(
            form.request_form_inventory_out_of_stock_notify_enabled.data
        )
        cfg.request_form_inventory_out_of_stock_notify_mode = (
            (form.request_form_inventory_out_of_stock_notify_mode.data or "email")
            .strip()
            .lower()
        )
        if cfg.request_form_inventory_out_of_stock_notify_mode not in (
            "notification",
            "email",
            "both",
        ):
            cfg.request_form_inventory_out_of_stock_notify_mode = "email"
        cfg.request_form_inventory_out_of_stock_message = (
            form.request_form_inventory_out_of_stock_message.data or ""
        ).strip() or None

        cfg.nudge_enabled = bool(form.nudge_enabled.data)
        # store value as float; the form supplies a string from the select
        try:
            cfg.nudge_interval_hours = float(form.nudge_interval_hours.data or 24)
        except Exception:
            cfg.nudge_interval_hours = 24.0
        # enforce minimum allowed (4 hours); admin may only extend beyond this
        try:
            requested = int(form.nudge_min_delay_hours.data or 4)
        except Exception:
            requested = 4
        if requested < 4:
            requested = 4
            flash(
                "Minimum nudge delay cannot be less than 4 hours; adjusted to 4.",
                "warning",
            )
        cfg.nudge_min_delay_hours = requested

        db.session.commit()
        flash("Nudge / special email settings saved.", "success")
        return redirect(url_for("admin.special_email"))

    return render_template("admin_special_email.html", form=form, cfg=cfg)


@admin_bp.route("/email_routing")
@login_required
def email_routing_list():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from ..models import EmailRouting

    rows = EmailRouting.query.order_by(EmailRouting.recipient_email.asc()).all()
    return render_template("admin_email_routing.html", rows=rows)


@admin_bp.route("/email_routing/new", methods=["GET", "POST"])
@login_required
def email_routing_new():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from .forms import EmailRoutingForm

    form = EmailRoutingForm()
    if form.validate_on_submit():
        from ..models import EmailRouting

        r = EmailRouting(
            recipient_email=form.recipient_email.data.strip().lower(),
            department_code=form.department_code.data.strip().upper(),
        )
        db.session.add(r)
        db.session.commit()
        flash("Email routing mapping created.", "success")
        return redirect(url_for("admin.email_routing_list"))
    return render_template("admin_email_routing_form.html", form=form)


@admin_bp.route("/assignments")
@login_required
def list_assignments():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    rows = DepartmentFormAssignment.query.order_by(
        DepartmentFormAssignment.department_name.asc()
    ).all()
    # load templates map for display
    templates = {
        t.id: t for t in FormTemplate.query.order_by(FormTemplate.name.asc()).all()
    }
    return render_template("admin_assignments.html", rows=rows, templates=templates)


@admin_bp.route("/webhooks")
@login_required
def list_webhooks():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # Show recent external submissions (those with a template_id)
    rows = (
        Submission.query.filter(Submission.template_id.isnot(None))
        .order_by(Submission.created_at.desc())
        .limit(200)
        .all()
    )
    templates = {
        t.id: t for t in FormTemplate.query.order_by(FormTemplate.name.asc()).all()
    }
    return render_template("admin_webhooks.html", rows=rows, templates=templates)


@admin_bp.route("/assignments/new", methods=["GET", "POST"])
@login_required
def new_assignment():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = DepartmentAssignmentForm()
    form.template_id.choices = [
        (t.id, t.name)
        for t in FormTemplate.query.order_by(FormTemplate.name.asc()).all()
    ]
    if form.validate_on_submit():
        # ensure one assignment per department (replace existing)
        DepartmentFormAssignment.query.filter_by(
            department_name=form.department.data
        ).delete()
        a = DepartmentFormAssignment(
            template_id=form.template_id.data, department_name=form.department.data
        )
        db.session.add(a)
        db.session.commit()
        flash("Template assigned to department.", "success")
        return redirect(url_for("admin.list_assignments"))

    return render_template("admin_assignments.html", form=form, rows=[], templates={})


@admin_bp.route("/assignments/<int:assignment_id>/delete", methods=["POST"])
@login_required
def delete_assignment(assignment_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    a = get_or_404(DepartmentFormAssignment, assignment_id)
    db.session.delete(a)
    db.session.commit()
    flash("Assignment removed.", "success")
    return redirect(url_for("admin.list_assignments"))


@admin_bp.route("/email_routing/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def email_routing_edit(rid: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from ..models import EmailRouting

    r = get_or_404(EmailRouting, rid)
    from .forms import EmailRoutingForm

    form = EmailRoutingForm(obj=r)
    if form.validate_on_submit():
        r.recipient_email = form.recipient_email.data.strip().lower()
        r.department_code = form.department_code.data.strip().upper()
        db.session.commit()
        flash("Email routing mapping updated.", "success")
        return redirect(url_for("admin.email_routing_list"))
    return render_template("admin_email_routing_form.html", form=form, edit=r)


@admin_bp.route("/email_routing/<int:rid>/delete", methods=["POST"])
@login_required
def email_routing_delete(rid: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from ..models import EmailRouting

    r = get_or_404(EmailRouting, rid)
    db.session.delete(r)
    db.session.commit()
    flash("Email routing mapping deleted.", "success")
    return redirect(url_for("admin.email_routing_list"))


@admin_bp.route("/feature_flags", methods=["GET", "POST"])
@login_required
def feature_flags():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from .forms import FeatureFlagsForm

    # Ensure any prior aborted DB transaction is cleared before reading flags.
    try:
        db.session.rollback()
    except Exception:
        pass
    try:
        flags = FeatureFlags.get()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        flags = FeatureFlags()
    form = FeatureFlagsForm()
    if flask_request.method == "GET":
        form.enable_notifications.data = bool(
            getattr(flags, "enable_notifications", True)
        )
        form.enable_nudges.data = bool(getattr(flags, "enable_nudges", True))
        form.allow_user_nudges.data = bool(getattr(flags, "allow_user_nudges", False))
        form.vibe_enabled.data = bool(getattr(flags, "vibe_enabled", True))
        form.sso_admin_sync_enabled.data = bool(
            getattr(flags, "sso_admin_sync_enabled", True)
        )
        form.enable_external_forms.data = bool(
            getattr(flags, "enable_external_forms", False)
        )
        form.rolling_quotes_enabled.data = bool(
            getattr(flags, "rolling_quotes_enabled", True)
        )

    if form.validate_on_submit():
        flags.enable_notifications = bool(form.enable_notifications.data)
        flags.enable_nudges = bool(form.enable_nudges.data)
        flags.allow_user_nudges = bool(form.allow_user_nudges.data)
        flags.vibe_enabled = bool(form.vibe_enabled.data)
        flags.sso_admin_sync_enabled = bool(form.sso_admin_sync_enabled.data)
        flags.enable_external_forms = bool(
            getattr(form, "enable_external_forms", None)
            and form.enable_external_forms.data
        )
        flags.rolling_quotes_enabled = bool(
            getattr(form, "rolling_quotes_enabled", None)
            and form.rolling_quotes_enabled.data
        )
        db.session.commit()
        flash("Feature flags updated.", "success")
        return redirect(url_for("admin.feature_flags"))

    return render_template("admin_feature_flags.html", form=form, flags=flags)


@admin_bp.route("/metrics_config", methods=["GET", "POST"])
@login_required
def metrics_config():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from .forms import MetricsConfigForm
    from ..models import MetricsConfig
    from ..services.process_metrics import build_process_metrics_summary

    def build_admin_metrics_explorer_context():
        allowed_depts = ["A", "B", "C"]
        range_key = (flask_request.args.get("range") or "weekly").lower()
        selected_dept = (flask_request.args.get("dept") or "").strip().upper()
        visible_depts = [selected_dept] if selected_dept in allowed_depts else allowed_depts
        query = (flask_request.args.get("q") or "").strip()
        user_filters = flask_request.args.getlist("user")

        snapshot = build_process_metrics_summary(
            range_key=range_key,
            depts=visible_depts,
            query=query,
        )

        if user_filters:
            snapshot["users"] = [
                row
                for row in snapshot.get("users", [])
                if str(row.get("user_id")) in user_filters
                or row.get("email") in user_filters
            ]

        available_users = snapshot.get("users", []) if not user_filters else []
        if user_filters:
            unfiltered = build_process_metrics_summary(
                range_key=range_key,
                depts=visible_depts,
                query=query,
            )
            available_users = unfiltered.get("users", [])

        dept_buckets = []
        for dept_metrics in snapshot["by_dept"]:
            dept_code = dept_metrics["dept"]
            dept_buckets.append(
                {
                    "dept": dept_code,
                    "metrics": dept_metrics,
                    "users": [
                        row
                        for row in snapshot["users"]
                        if (row.get("department") or "").strip().upper() == dept_code
                    ],
                    "interactions": [
                        row
                        for row in snapshot["interactions"]
                        if row.get("from_department") == dept_code
                        or row.get("to_department") == dept_code
                    ],
                }
            )

        return {
            "metrics": snapshot["by_dept"],
            "dept_buckets": dept_buckets,
            "users": snapshot["users"],
            "interactions": snapshot["interactions"],
            "summary": snapshot["summary"],
            "now": snapshot["now"],
            "cutoff": snapshot["cutoff"],
            "range_label": snapshot["range_label"],
            "range_key": snapshot["range_key"],
            "allowed_metric_departments": allowed_depts,
            "selected_metric_department": selected_dept,
            "q": query,
            "user_filters": user_filters,
            "available_users": available_users,
        }

    try:
        db.session.rollback()
    except Exception:
        pass

    try:
        cfg = MetricsConfig.get()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        cfg = MetricsConfig()

    form = MetricsConfigForm()
    if flask_request.method == "GET":
        form.enabled.data = bool(getattr(cfg, "enabled", True))
        form.track_request_created.data = bool(
            getattr(cfg, "track_request_created", True)
        )
        form.track_assignments.data = bool(getattr(cfg, "track_assignments", True))
        form.track_status_changes.data = bool(
            getattr(cfg, "track_status_changes", True)
        )
        form.lookback_days.data = int(getattr(cfg, "lookback_days", 30) or 30)
        form.user_metrics_limit.data = int(
            getattr(cfg, "user_metrics_limit", 15) or 15
        )
        form.target_completion_hours.data = int(
            getattr(cfg, "target_completion_hours", 48) or 48
        )
        form.slow_event_threshold_hours.data = int(
            getattr(cfg, "slow_event_threshold_hours", 8) or 8
        )

    if form.validate_on_submit():
        cfg.enabled = bool(form.enabled.data)
        cfg.track_request_created = bool(form.track_request_created.data)
        cfg.track_assignments = bool(form.track_assignments.data)
        cfg.track_status_changes = bool(form.track_status_changes.data)
        cfg.lookback_days = max(int(form.lookback_days.data or 30), 1)
        cfg.user_metrics_limit = max(int(form.user_metrics_limit.data or 15), 1)
        cfg.target_completion_hours = max(
            int(form.target_completion_hours.data or 48), 1
        )
        cfg.slow_event_threshold_hours = max(
            int(form.slow_event_threshold_hours.data or 8), 1
        )
        db.session.add(cfg)
        db.session.commit()
        flash("Metrics settings updated.", "success")
        return redirect(url_for("admin.metrics_config"))

    explorer = build_admin_metrics_explorer_context()
    return render_template(
        "admin_metrics_config.html",
        form=form,
        cfg=cfg,
        snapshot=build_process_metrics_summary(range_key="weekly", depts=["A", "B", "C"]),
        explorer=explorer,
    )


@admin_bp.route("/metrics_overview", methods=["GET"])
@login_required
def metrics_overview():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from ..services.process_metrics import build_process_metrics_summary

    allowed_depts = ["A", "B", "C"]
    range_key = (flask_request.args.get("range") or "weekly").lower()
    selected_dept = (flask_request.args.get("dept") or "").strip().upper()
    visible_depts = [selected_dept] if selected_dept in allowed_depts else allowed_depts
    query = (flask_request.args.get("q") or "").strip()
    user_filters = flask_request.args.getlist("user")

    snapshot = build_process_metrics_summary(
        range_key=range_key,
        depts=visible_depts,
        query=query,
    )

    if user_filters:
        snapshot["users"] = [
            row
            for row in snapshot.get("users", [])
            if str(row.get("user_id")) in user_filters
            or row.get("email") in user_filters
        ]

    available_users = snapshot.get("users", []) if not user_filters else []
    if user_filters:
        unfiltered = build_process_metrics_summary(
            range_key=range_key,
            depts=visible_depts,
            query=query,
        )
        available_users = unfiltered.get("users", [])

    dept_buckets = []
    for dept_metrics in snapshot["by_dept"]:
        dept_code = dept_metrics["dept"]
        dept_buckets.append(
            {
                "dept": dept_code,
                "metrics": dept_metrics,
                "users": [
                    row
                    for row in snapshot["users"]
                    if (row.get("department") or "").strip().upper() == dept_code
                ],
                "interactions": [
                    row
                    for row in snapshot["interactions"]
                    if row.get("from_department") == dept_code
                    or row.get("to_department") == dept_code
                ],
            }
        )

    return render_template(
        "metrics.html",
        metrics=snapshot["by_dept"],
        dept_buckets=dept_buckets,
        users=snapshot["users"],
        interactions=snapshot["interactions"],
        summary=snapshot["summary"],
        now=snapshot["now"],
        cutoff=snapshot["cutoff"],
        range_label=snapshot["range_label"],
        range_key=snapshot["range_key"],
        allowed_metric_departments=allowed_depts,
        selected_metric_department=selected_dept,
        q=query,
        user_filters=user_filters,
        available_users=available_users,
        admin_metrics_mode=True,
        metrics_view_endpoint="admin.metrics_overview",
    )


@admin_bp.route("/reject_request_config", methods=["GET", "POST"])
@login_required
def reject_request_config():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    from .forms import RejectRequestConfigForm

    cfg = RejectRequestConfig.get()
    form = RejectRequestConfigForm()

    if flask_request.method == "GET":
        form.enabled.data = bool(getattr(cfg, "enabled", True))
        form.button_label.data = (
            getattr(cfg, "button_label", "Reject Request") or "Reject Request"
        )
        form.rejection_message.data = getattr(cfg, "rejection_message", None)
        form.dept_a_enabled.data = bool(getattr(cfg, "dept_a_enabled", False))
        form.dept_b_enabled.data = bool(getattr(cfg, "dept_b_enabled", True))
        form.dept_c_enabled.data = bool(getattr(cfg, "dept_c_enabled", False))

    if form.validate_on_submit():
        cfg.enabled = bool(form.enabled.data)
        cfg.button_label = (form.button_label.data or "Reject Request").strip()[:120]
        cfg.rejection_message = (form.rejection_message.data or "").strip() or None
        cfg.dept_a_enabled = bool(form.dept_a_enabled.data)
        cfg.dept_b_enabled = bool(form.dept_b_enabled.data)
        cfg.dept_c_enabled = bool(form.dept_c_enabled.data)
        db.session.commit()
        flash("Reject request configuration updated.", "success")
        return redirect(url_for("admin.reject_request_config"))

    return render_template("admin_reject_request_config.html", form=form, cfg=cfg)


@admin_bp.route("/departments")
@login_required
def list_departments():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    depts = Department.query.order_by(Department.code).all()
    return render_template("admin_departments.html", departments=depts)


@admin_bp.route("/status_options")
@login_required
def list_status_options():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # load existing options, but if none are present try to bootstrap from any
    # workflows that might exist.  this helps new installs or cases where the
    # workflow page has been used but the admin never clicked "implement".
    opts = []
    try:
        opts = StatusOption.query.order_by(StatusOption.code).all()
    except Exception:
        # Defensive: if DB schema is out-of-date (missing columns), avoid 500
        # and show an empty list with a helpful admin notice.
        current_app.logger.exception(
            "Failed to load StatusOption rows for admin list; DB schema may be missing migrations"
        )
        try:
            inspector = db.inspect(db.engine)
            table_name = StatusOption.__tablename__
            if not inspector.has_table(table_name):
                try:
                    StatusOption.__table__.create(bind=db.engine)
                    flash(
                        "Status options table was missing and has been created. Please run `alembic upgrade head` to synchronize migrations.",
                        "warning",
                    )
                except Exception:
                    current_app.logger.exception("Failed to create StatusOption table")
                    flash(
                        "Status options could not be loaded. Ensure DB migrations have been applied (run alembic upgrade head).",
                        "danger",
                    )
                opts = []
            else:
                existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
                model_cols = {c.name for c in StatusOption.__table__.columns}
                missing = model_cols - existing_cols
                if missing:
                    flash(
                        f"Status options schema mismatch: missing columns: {', '.join(sorted(missing))}. Run `alembic upgrade head`.",
                        "danger",
                    )
                else:
                    flash(
                        "Status options could not be loaded due to an unexpected database error. Check application logs for details.",
                        "danger",
                    )
                opts = []
        except Exception:
            current_app.logger.exception("Failed to inspect DB schema for StatusOption")
            flash(
                "Status options could not be loaded. Ensure DB migrations have been applied (run alembic upgrade head).",
                "danger",
            )
            opts = []

    # if the table exists but is currently empty, attempt to derive rows from any
    # existing workflows so the admin has something visible immediately.
    if not opts:
        try:
            generated = False
            for wf in Workflow.query.all():
                spec = _normalize_workflow_spec(wf.spec, wf.name)
                steps = spec.get("steps") or []
                for step in steps:
                    code = None
                    target_dept = None
                    if isinstance(step, dict):
                        code = step.get("status") or step.get("code")
                        target_dept = step.get("to_dept") or step.get("to")
                    elif isinstance(step, str):
                        code = step
                    if not code:
                        continue
                    if not StatusOption.query.filter_by(code=code).first():
                        label = code.replace("_", " ").title()
                        opt = StatusOption(code=code, label=label)
                        if target_dept:
                            opt.target_department = target_dept or None
                        db.session.add(opt)
                        generated = True
            if generated:
                db.session.commit()
                flash("Status options generated from existing workflows.", "info")
                opts = StatusOption.query.order_by(StatusOption.code).all()
        except Exception:
            # if something goes wrong here just log and continue with empty list
            current_app.logger.exception("Failed to bootstrap status options from workflows")

    return render_template("admin_status_options.html", status_options=opts)


@admin_bp.route("/migrations/status")
@login_required
def migration_status():
    """Admin helper: show applied DB alembic version(s) and migration files.

    This view is read-only and intended to help administrators detect
    unapplied migrations and provide the exact command to run (alembic upgrade head).
    """
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    try:
        inspector = db.inspect(db.engine)
    except Exception:
        current_app.logger.exception("Failed to inspect DB engine for migration status")
        flash(
            "Unable to inspect database engine. Check server logs.", "danger"
        )
        return render_template("admin_migration_status.html", status=None)

    # gather migration scripts from migrations/versions
    import os
    versions_dir = os.path.join(current_app.root_path, "..", "migrations", "versions")
    migrations = []
    try:
        for fn in sorted(os.listdir(versions_dir)):
            if fn.endswith('.py') and not fn.startswith('__'):
                migrations.append(fn[:-3])
    except Exception:
        migrations = []

    db_versions = []
    try:
        if inspector.has_table('alembic_version'):
            res = db.session.execute('SELECT version_num FROM alembic_version')
            db_versions = [r[0] for r in res.fetchall()]
    except Exception:
        current_app.logger.exception('Failed to read alembic_version table')

    status = {
        'migration_files': migrations,
        'db_versions': db_versions,
    }

    # Determine if any migration files look unapplied by comparing names.
    unapplied = [m for m in migrations if m not in db_versions]
    status['unapplied'] = unapplied

    return render_template("admin_migration_status.html", status=status)


@admin_bp.route("/status_options/new", methods=["GET", "POST"])
@login_required
def create_status_option():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
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
            notify_to_originator_only=bool(
                getattr(form, "notify_to_originator_only", False).data
                if getattr(form, "notify_to_originator_only", None)
                else False
            ),
            email_enabled=bool(
                getattr(form, "email_enabled", False).data
                if getattr(form, "email_enabled", None)
                else False
            ),
            screenshot_required=bool(
                getattr(form, "screenshot_required", False).data
                if getattr(form, "screenshot_required", None)
                else False
            ),
        )
        db.session.add(opt)
        db.session.commit()
        flash("Status option created.", "success")
        return redirect(url_for("admin.list_status_options"))
    return render_template("admin_status_edit.html", form=form)


@admin_bp.route("/status_options/<int:opt_id>/edit", methods=["GET", "POST"])
@login_required
def edit_status_option(opt_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    from .forms import StatusOptionForm

    opt = get_or_404(StatusOption, opt_id)
    form = StatusOptionForm(obj=opt)
    if form.validate_on_submit():
        opt.code = form.code.data.strip()
        opt.label = form.label.data.strip()
        opt.target_department = form.target_department.data or None
        opt.notify_enabled = bool(form.notify_enabled.data)
        opt.notify_on_transfer_only = bool(form.notify_on_transfer_only.data)
        opt.notify_to_originator_only = bool(
            getattr(form, "notify_to_originator_only", False).data
            if getattr(form, "notify_to_originator_only", None)
            else False
        )
        opt.email_enabled = bool(
            getattr(form, "email_enabled", False).data
            if getattr(form, "email_enabled", None)
            else False
        )
        opt.screenshot_required = bool(
            getattr(form, "screenshot_required", False).data
            if getattr(form, "screenshot_required", None)
            else False
        )
        db.session.commit()
        flash("Status option updated.", "success")
        return redirect(url_for("admin.list_status_options"))
    return render_template("admin_status_edit.html", form=form, opt=opt)


@admin_bp.route("/status_options/<int:opt_id>/delete", methods=["POST"])
@login_required
def delete_status_option(opt_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    opt = get_or_404(StatusOption, opt_id)
    db.session.delete(opt)
    db.session.commit()
    flash("Status option deleted.", "success")
    return redirect(url_for("admin.list_status_options"))


@admin_bp.route("/status_options/<int:opt_id>/toggle_screenshot", methods=["POST"])
@login_required
def toggle_status_screenshot(opt_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    opt = get_or_404(StatusOption, opt_id)
    try:
        opt.screenshot_required = not bool(opt.screenshot_required)
        db.session.commit()
        flash("Screenshot requirement updated.", "success")
    except Exception:
        db.session.rollback()
        flash("Failed to update screenshot requirement.", "danger")
    return redirect(url_for("admin.list_status_options"))


@admin_bp.route("/status_options/<int:opt_id>/toggle_notify_scope", methods=["POST"])
@login_required
def toggle_status_notify_scope(opt_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    opt = get_or_404(StatusOption, opt_id)
    try:
        opt.notify_to_originator_only = not bool(
            getattr(opt, "notify_to_originator_only", False)
        )
        db.session.commit()
        flash("Notification scope updated.", "success")
    except Exception:
        db.session.rollback()
        flash("Failed to update notification scope.", "danger")
    return redirect(url_for("admin.list_status_options"))


@admin_bp.route("/status_options/<int:opt_id>/toggle_email", methods=["POST"])
@login_required
def toggle_status_email(opt_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    opt = get_or_404(StatusOption, opt_id)
    try:
        opt.email_enabled = not bool(getattr(opt, "email_enabled", False))
        db.session.commit()
        flash("Email setting updated for that status.", "success")
    except Exception:
        db.session.rollback()
        flash("Failed to update email setting.", "danger")
    return redirect(url_for("admin.list_status_options"))


@admin_bp.route("/dept_editors")
@login_required
def list_dept_editors():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    editors = DepartmentEditor.query.order_by(
        DepartmentEditor.department, DepartmentEditor.assigned_at.desc()
    ).all()
    return render_template("admin_dept_editors.html", editors=editors)


@admin_bp.route("/integrations")
@login_required
def list_integrations():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    ints = IntegrationConfig.query.order_by(
        IntegrationConfig.department, IntegrationConfig.kind
    ).all()
    summaries = {i.id: integration_config_summary(i.config) for i in ints}
    return render_template(
        "admin_integrations.html",
        integrations=ints,
        summaries=summaries,
    )


@admin_bp.route("/buckets/import_default", methods=["POST"])
@login_required
def import_default_buckets():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # Recommended default buckets for Dept B (used by tests)
    try:
        # In Progress bucket
        b = StatusBucket.query.filter_by(
            name="In Progress", department_name="B"
        ).first()
        if not b:
            b = StatusBucket(
                name="In Progress", department_name="B", order=0, active=True
            )
            db.session.add(b)
            db.session.flush()
            bs = BucketStatus(bucket_id=b.id, status_code="B_IN_PROGRESS", order=0)
            db.session.add(bs)

        # Waiting bucket
        w = StatusBucket.query.filter_by(name="Waiting", department_name="B").first()
        if not w:
            w = StatusBucket(name="Waiting", department_name="B", order=1, active=True)
            db.session.add(w)
            db.session.flush()
            ws = BucketStatus(
                bucket_id=w.id, status_code="WAITING_ON_A_RESPONSE", order=0
            )
            db.session.add(ws)

        db.session.commit()
        flash("Imported recommended buckets.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to import default buckets")
        flash("Failed to import buckets.", "danger")
    return redirect(url_for("admin.list_departments"))


@admin_bp.route("/buckets")
@login_required
def list_buckets():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    buckets = StatusBucket.query.order_by(
        StatusBucket.department_name.asc().nullsfirst(), StatusBucket.order.asc()
    ).all()
    return render_template("admin_buckets.html", buckets=buckets)


@admin_bp.route("/buckets/new", methods=["GET", "POST"])
@login_required
def buckets_new():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    form = StatusBucketForm()
    # populate workflow choices (global + any department-scoped active workflows)
    wfs = (
        Workflow.query.filter(Workflow.active == True)
        .order_by(Workflow.name.asc())
        .all()
    )
    form.workflow_id.choices = [(0, "-- None --")] + [
        (w.id, w.name + (f" (Dept {w.department_code})" if w.department_code else ""))
        for w in wfs
    ]

    if form.validate_on_submit():
        b = StatusBucket(
            name=form.name.data.strip(),
            department_name=(form.department_name.data or None) or None,
            order=int(form.order.data or 0),
            active=bool(form.active.data),
        )
        # assign workflow if selected
        try:
            sel = int(form.workflow_id.data or 0)
        except Exception:
            sel = 0
        if sel:
            b.workflow_id = sel
        db.session.add(b)
        db.session.commit()
        flash("Bucket created.", "success")
        return redirect(url_for("admin.list_buckets"))
    return render_template("admin_bucket_form.html", form=form)


@admin_bp.route("/buckets/<int:bucket_id>/edit", methods=["GET", "POST"])
@login_required
def buckets_edit(bucket_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    b = get_or_404(StatusBucket, bucket_id)
    form = StatusBucketForm(obj=b)
    # populate workflow choices scoped to department (or global)
    if b.department_name:
        wfs = (
            Workflow.query.filter(
                (Workflow.department_code == None)
                | (Workflow.department_code == b.department_name)
            )
            .filter(Workflow.active == True)
            .order_by(Workflow.name.asc())
            .all()
        )
    else:
        wfs = (
            Workflow.query.filter(Workflow.active == True)
            .order_by(Workflow.name.asc())
            .all()
        )
    form.workflow_id.choices = [(0, "-- None --")] + [
        (w.id, w.name + (f" (Dept {w.department_code})" if w.department_code else ""))
        for w in wfs
    ]
    # prefill selected workflow in form when GET
    if flask_request.method == "GET":
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
        flash("Bucket updated.", "success")
        # handle bulk-add statuses if provided
        bulk = (form.bulk_statuses.data or "").strip()
        if bulk:
            lines = [l.strip() for l in bulk.splitlines() if l.strip()]
            if lines:
                # compute next order base
                existing = b.statuses.order_by(BucketStatus.order.desc()).first()
                base = existing.order + 1 if existing else 0
                for idx, code in enumerate(lines):
                    ns = BucketStatus(
                        bucket_id=b.id, status_code=code, order=base + idx
                    )
                    db.session.add(ns)
                db.session.commit()
                flash(f"Added {len(lines)} statuses to bucket.", "success")
        return redirect(url_for("admin.list_buckets"))

    # handle adding a new status code via POST param (supports select or free text)
    if flask_request.method == "POST" and (
        flask_request.form.get("new_status_code")
        or flask_request.form.get("new_status_code_select")
    ):
        code = (
            flask_request.form.get("new_status_code_select")
            or flask_request.form.get("new_status_code")
            or ""
        ).strip()
        try:
            ordv = int(flask_request.form.get("new_status_order") or 0)
        except Exception:
            ordv = 0
        if code:
            ns = BucketStatus(bucket_id=b.id, status_code=code, order=ordv)
            db.session.add(ns)
            db.session.commit()
            flash("Added status to bucket.", "success")
        return redirect(url_for("admin.buckets_edit", bucket_id=b.id))

    statuses = b.statuses.order_by(BucketStatus.order.asc()).all()

    # Load available status options and workflows scoped to this bucket's department
    if b.department_name:
        status_opts = (
            StatusOption.query.filter(
                (StatusOption.target_department == None)
                | (StatusOption.target_department == b.department_name)
            )
            .order_by(StatusOption.code.asc())
            .all()
        )
        workflows = (
            Workflow.query.filter(
                (Workflow.department_code == None)
                | (Workflow.department_code == b.department_name)
            )
            .filter(Workflow.active == True)
            .order_by(Workflow.name.asc())
            .all()
        )
    else:
        status_opts = StatusOption.query.order_by(StatusOption.code.asc()).all()
        workflows = (
            Workflow.query.filter(Workflow.active == True)
            .order_by(Workflow.name.asc())
            .all()
        )

    return render_template(
        "admin_bucket_form.html",
        form=form,
        bucket=b,
        statuses=statuses,
        status_options=status_opts,
        workflows=workflows,
    )


@admin_bp.route("/buckets/<int:bucket_id>/delete", methods=["POST"])
@login_required
def buckets_delete(bucket_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    b = get_or_404(StatusBucket, bucket_id)
    db.session.delete(b)
    db.session.commit()
    flash("Bucket deleted.", "success")
    return redirect(url_for("admin.list_buckets"))


@admin_bp.route(
    "/buckets/<int:bucket_id>/status/<int:status_id>/delete", methods=["POST"]
)
@login_required
def buckets_status_delete(bucket_id: int, status_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    s = get_or_404(BucketStatus, status_id)
    db.session.delete(s)
    db.session.commit()
    flash("Bucket status removed.", "success")
    return redirect(url_for("admin.buckets_edit", bucket_id=bucket_id))


@admin_bp.route("/buckets/<int:bucket_id>/reorder_statuses", methods=["POST"])
@login_required
def buckets_reorder_statuses(bucket_id: int):
    if not _is_admin_user():
        return jsonify({"error": "access_denied"}), 403

    b = get_or_404(StatusBucket, bucket_id)
    try:
        payload = flask_request.get_json(force=True)
    except Exception:
        payload = None
    if (
        not payload
        or "order" not in payload
        or not isinstance(payload.get("order"), list)
    ):
        return jsonify({"error": "invalid_payload"}), 400

    ids = [int(x) for x in payload.get("order") if str(x).isdigit()]
    # ensure all ids belong to this bucket
    items = {
        s.id: s
        for s in BucketStatus.query.filter(
            BucketStatus.bucket_id == b.id, BucketStatus.id.in_(ids)
        ).all()
    }
    # apply new order
    for idx, sid in enumerate(ids):
        s = items.get(sid)
        if s:
            s.order = int(idx)
            db.session.add(s)
    db.session.commit()
    return jsonify({"ok": True})


@admin_bp.route("/integrations/new", methods=["GET", "POST"])
@login_required
def create_integration():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    from .forms import IntegrationConfigForm

    form = IntegrationConfigForm()
    selected_kind = form.kind.data or (form.kind.choices[0][0] if form.kind.choices else "webhook")
    if form.validate_on_submit():
        try:
            normalized = normalize_integration_config(
                form.kind.data, form.config_json.data
            )
        except Exception as exc:
            flash(str(exc), "danger")
            scaffold = get_integration_scaffold(form.kind.data)
            return render_template(
                "admin_integration_edit.html",
                form=form,
                scaffold=scaffold,
                integration_scaffolds=INTEGRATION_KIND_SCAFFOLDS,
            )
        ic = IntegrationConfig(
            department=form.department.data,
            kind=form.kind.data,
            enabled=bool(form.enabled.data),
            config=json.dumps(normalized, indent=2),
        )
        db.session.add(ic)
        db.session.commit()
        flash("Integration saved.", "success")
        return redirect(url_for("admin.list_integrations"))
    if not form.config_json.data:
        form.config_json.data = json.dumps(
            get_integration_scaffold(selected_kind).get("default_config") or {},
            indent=2,
        )
    return render_template(
        "admin_integration_edit.html",
        form=form,
        scaffold=get_integration_scaffold(selected_kind),
        integration_scaffolds=INTEGRATION_KIND_SCAFFOLDS,
    )


@admin_bp.route("/integrations/<int:int_id>/edit", methods=["GET", "POST"])
@login_required
def edit_integration(int_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    from .forms import IntegrationConfigForm

    ic = get_or_404(IntegrationConfig, int_id)
    form = IntegrationConfigForm(obj=ic)
    if flask_request.method == "GET":
        try:
            normalized = normalize_integration_config(ic.kind, ic.config)
            form.config_json.data = json.dumps(normalized, indent=2)
        except Exception:
            form.config_json.data = ic.config or ""
    if form.validate_on_submit():
        try:
            normalized = normalize_integration_config(
                form.kind.data, form.config_json.data
            )
        except Exception as exc:
            flash(str(exc), "danger")
            return render_template(
                "admin_integration_edit.html",
                form=form,
                integration=ic,
                scaffold=get_integration_scaffold(form.kind.data),
                integration_scaffolds=INTEGRATION_KIND_SCAFFOLDS,
            )
        ic.department = form.department.data
        ic.kind = form.kind.data
        ic.enabled = bool(form.enabled.data)
        ic.config = json.dumps(normalized, indent=2)
        db.session.commit()
        flash("Integration updated.", "success")
        return redirect(url_for("admin.list_integrations"))
    return render_template(
        "admin_integration_edit.html",
        form=form,
        integration=ic,
        scaffold=get_integration_scaffold(ic.kind),
        integration_scaffolds=INTEGRATION_KIND_SCAFFOLDS,
    )


@admin_bp.route("/integrations/<int:int_id>/delete", methods=["POST"])
@login_required
def delete_integration(int_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    ic = get_or_404(IntegrationConfig, int_id)
    db.session.delete(ic)
    db.session.commit()
    flash("Integration removed.", "success")
    return redirect(url_for("admin.list_integrations"))


@admin_bp.route("/dept_editors/new", methods=["GET", "POST"])
@login_required
def create_dept_editor():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    from .forms import DepartmentEditorForm

    form = DepartmentEditorForm()
    # populate user choices
    form.user_id.choices = [
        (u.id, u.email) for u in User.query.order_by(User.email).all()
    ]
    if form.validate_on_submit():
        de = DepartmentEditor(
            user_id=form.user_id.data,
            department=form.department.data,
            can_edit=bool(form.can_edit.data),
            can_view_metrics=bool(form.can_view_metrics.data),
        )
        db.session.add(de)
        db.session.commit()
        flash("Department editor created.", "success")
        return redirect(url_for("admin.list_dept_editors"))
    return render_template("admin_dept_editor_edit.html", form=form)


@admin_bp.route("/dept_editors/<int:de_id>/delete", methods=["POST"])
@login_required
def delete_dept_editor(de_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    de = get_or_404(DepartmentEditor, de_id)
    db.session.delete(de)
    db.session.commit()
    flash("Department editor removed.", "success")
    return redirect(url_for("admin.list_dept_editors"))


@admin_bp.route("/departments/new", methods=["GET", "POST"])
@login_required
def create_department():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    form = DepartmentForm()
    if form.validate_on_submit():
        d = Department(
            code=form.code.data.upper(),
            label=form.name.data,
            description=None,
            is_active=bool(form.active.data),
            order=int(form.order.data or 0),
        )
        db.session.add(d)
        db.session.commit()
        flash("Department created.", "success")
        return redirect(url_for("admin.list_departments"))
    return render_template("admin_department_edit.html", form=form)


@admin_bp.route("/departments/<int:dept_id>/edit", methods=["GET", "POST"])
@login_required
def edit_department(dept_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    d = get_or_404(Department, dept_id)
    form = DepartmentForm(obj=d)
    if form.validate_on_submit():
        d.code = form.code.data.upper()
        d.label = form.name.data
        d.order = int(form.order.data or 0)
        d.is_active = bool(form.active.data)
        db.session.commit()
        flash("Department updated.", "success")
        return redirect(url_for("admin.list_departments"))
    return render_template("admin_department_edit.html", form=form, dept=d)


@admin_bp.route("/departments/<int:dept_id>/delete", methods=["POST"])
@login_required
def delete_department(dept_id: int):
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    d = get_or_404(Department, dept_id)
    db.session.delete(d)
    db.session.commit()
    flash("Department deleted.", "success")
    return jsonify({"ok": True})
