from datetime import datetime, timedelta
from typing import Optional
import uuid

from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    session,
    request as flask_request,
    current_app,
    Response,
)
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from .routes import admin_bp
from .forms import (
    AdminCreateUserForm,
    SSOAssignForm,
    BulkDepartmentAssignForm,
)
from ..extensions import db, get_or_404
from ..models import (
    User,
    Tenant,
    UserDepartment,
    AuditLog,
    DepartmentEditor,
    Department,
)
from ..services.tenant_context import ensure_user_tenant_membership
from ..utils.user_context import get_user_departments
from .utils import _is_admin_user


DEPARTMENT_CHOICES = [("A", "A"), ("B", "B"), ("C", "C")]


def _available_department_codes(include_codes=None) -> list[str]:
    codes = []
    try:
        rows = Department.query.filter_by(is_active=True).order_by(Department.order.asc(), Department.code.asc()).all()
        codes.extend((row.code or "").strip().upper() for row in rows)
    except Exception:
        pass
    if not codes:
        codes.extend(code for code, _label in DEPARTMENT_CHOICES)
    for code in include_codes or []:
        cleaned = str(code or "").strip().upper()
        if cleaned:
            codes.append(cleaned)
    return list(dict.fromkeys(code for code in codes if code))


def _available_department_choices(include_codes=None) -> list[tuple[str, str]]:
    codes = _available_department_codes(include_codes=include_codes)
    labels = {}
    try:
        rows = Department.query.filter(Department.code.in_(codes)).all()
        labels = {
            (row.code or "").strip().upper(): (row.label or row.code or "").strip()
            for row in rows
        }
    except Exception:
        labels = {}
    return [(code, labels.get(code) or code) for code in codes]


def _department_metadata_map(include_codes=None) -> dict[str, Department]:
    codes = _available_department_codes(include_codes=include_codes)
    try:
        rows = Department.query.filter(Department.code.in_(codes)).all()
    except Exception:
        rows = []
    return {(row.code or "").strip().upper(): row for row in rows}


def _coverage_entry_matches_query(entry: dict, query: str, department_meta: dict[str, Department]) -> bool:
    raw = str(query or "").strip().lower()
    if not raw:
        return True
    department = str(entry.get("department") or "").strip().upper()
    dept_obj = department_meta.get(department)
    fields = [
        getattr(entry.get("user"), "email", None),
        getattr(entry.get("user"), "name", None),
        department,
        getattr(dept_obj, "label", None),
        entry.get("note"),
        entry.get("handoff_doc_url"),
        getattr(entry.get("backup_approver"), "email", None),
    ]
    fields.extend(entry.get("handoff_checklist") or [])
    haystack = " ".join(str(item or "") for item in fields).lower()
    return raw in haystack


def _coverage_pair_matches_query(pair: dict, query: str, department_meta: dict[str, Department]) -> bool:
    raw = str(query or "").strip().lower()
    if not raw:
        return True
    labels = []
    for code in pair.get("departments") or []:
        labels.append(code)
        labels.append(getattr(department_meta.get(code), "label", None))
    haystack = " ".join(
        str(item or "")
        for item in [
            getattr(pair.get("user"), "email", None),
            getattr(pair.get("user"), "name", None),
            getattr(pair.get("backup"), "email", None),
            *(pair.get("notification_departments") or []),
            *labels,
        ]
    ).lower()
    return raw in haystack


def _parse_datetime_local(raw_value):
    raw = str(raw_value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    raise ValueError("Use a valid date/time.")


def _assignment_windows_overlap(start_a, end_a, start_b, end_b) -> bool:
    if not start_a or not end_a or not start_b or not end_b:
        return False
    return start_a < end_b and start_b < end_a


def _temporary_assignment_conflicts(user: User, starts_at, ends_at, exclude_assignment_id=None):
    if not user or not starts_at or not ends_at:
        return []
    conflicts = []
    for assignment in getattr(user, "departments", []) or []:
        if getattr(assignment, "id", None) == exclude_assignment_id:
            continue
        if str(getattr(assignment, "assignment_kind", "shared") or "shared").strip().lower() != "temporary":
            continue
        other_end = getattr(assignment, "expires_at", None)
        if not other_end or getattr(assignment, "is_active_assignment", True) is False:
            continue
        other_start = getattr(assignment, "created_at", None) or starts_at
        if _assignment_windows_overlap(starts_at, ends_at, other_start, other_end):
            conflicts.append(assignment)
    return conflicts


def _format_assignment_conflict_message(conflicts) -> str:
    if not conflicts:
        return ""
    parts = []
    for assignment in conflicts:
        dept = (getattr(assignment, "department", None) or "?").strip().upper()
        ends_at = getattr(assignment, "expires_at", None)
        if ends_at:
            parts.append(f"Dept {dept} until {ends_at.strftime('%b %d %H:%M')}")
        else:
            parts.append(f"Dept {dept}")
    return ", ".join(parts)


def _coverage_entry_conflicts(entries) -> list[dict]:
    annotated = []
    for entry in entries:
        overlaps = []
        for other in entries:
            if entry is other:
                continue
            if getattr(entry["assignment"], "id", None) == getattr(other["assignment"], "id", None):
                continue
            if getattr(entry["user"], "id", None) != getattr(other["user"], "id", None):
                continue
            if _assignment_windows_overlap(
                entry["starts_at"],
                entry["ends_at"],
                other["starts_at"],
                other["ends_at"],
            ):
                overlaps.append(other)
        entry["conflicts"] = overlaps
        entry["has_conflict"] = bool(overlaps)
        annotated.append(entry)
    return annotated


def _workflow_profile_config(profile_name: str) -> dict:
    return User.WORKFLOW_ROLE_PROFILES.get(
        str(profile_name or "member").strip().lower() or "member",
        User.WORKFLOW_ROLE_PROFILES["member"],
    )


def _sync_user_workflow_profile(user: User):
    if not user or not getattr(user, "id", None):
        return

    def _normalized_department(value):
        return (value or "").strip().upper()

    user_departments = get_user_departments(user)
    departments = [
        dept
        for dept in user_departments
        if dept in set(_available_department_codes(include_codes=user_departments))
    ]
    config = _workflow_profile_config(getattr(user, "workflow_role_profile", "member"))
    existing_rows = list(getattr(user, "dept_editor_roles", []) or [])
    existing_rows.extend(
        DepartmentEditor.query.filter_by(user_id=user.id).all()
    )
    existing_rows.extend(
        obj
        for obj in db.session.new
        if isinstance(obj, DepartmentEditor) and getattr(obj, "user_id", None) == user.id
    )
    existing_rows_by_department = {}
    for row in existing_rows:
        dept_key = _normalized_department(getattr(row, "department", None))
        if dept_key and dept_key not in existing_rows_by_department:
            existing_rows_by_department[dept_key] = row
    managed_rows = {
        _normalized_department(getattr(row, "department", None)): row
        for row in existing_rows
        if getattr(row, "managed_by_profile", False)
    }

    should_manage = any(
        bool(config.get(flag, False))
        for flag in ("can_edit", "can_view_metrics", "can_change_priority")
    )

    if not should_manage:
        for row in managed_rows.values():
            db.session.delete(row)
        return

    for dept in list(managed_rows.keys()):
        if dept not in departments:
            db.session.delete(managed_rows[dept])
            managed_rows.pop(dept, None)

    for dept in departments:
        row = managed_rows.get(dept) or existing_rows_by_department.get(dept)
        if not row:
            row = DepartmentEditor(user_id=user.id, department=dept, managed_by_profile=True)
            db.session.add(row)
        row.can_edit = bool(config.get("can_edit", False))
        row.can_view_metrics = bool(config.get("can_view_metrics", False))
        row.can_change_priority = bool(config.get("can_change_priority", False))
        row.managed_by_profile = True


def _dedupe_department_editor_rows(user: User):
    if not user or not getattr(user, "id", None):
        return

    def _normalized_department(value):
        return (value or "").strip().upper()

    with db.session.no_autoflush:
        rows = list(DepartmentEditor.query.filter_by(user_id=user.id).all())
        rows.extend(
            obj
            for obj in db.session.new
            if isinstance(obj, DepartmentEditor)
            and (getattr(obj, "user_id", None) == user.id or getattr(obj, "user", None) is user)
        )

    rows_by_department = {}
    for row in rows:
        dept_key = _normalized_department(getattr(row, "department", None))
        if not dept_key:
            continue
        rows_by_department.setdefault(dept_key, []).append(row)

    for dept_key, dept_rows in rows_by_department.items():
        if len(dept_rows) < 2:
            continue

        kept_row = next((row for row in dept_rows if getattr(row, "id", None)), dept_rows[0])
        for duplicate_row in dept_rows:
            if duplicate_row is kept_row:
                continue
            kept_row.department = dept_key
            kept_row.can_edit = bool(getattr(duplicate_row, "can_edit", False) or kept_row.can_edit)
            kept_row.can_view_metrics = bool(
                getattr(duplicate_row, "can_view_metrics", False) or kept_row.can_view_metrics
            )
            kept_row.can_change_priority = bool(
                getattr(duplicate_row, "can_change_priority", False)
                or kept_row.can_change_priority
            )
            kept_row.managed_by_profile = bool(
                getattr(duplicate_row, "managed_by_profile", False) or kept_row.managed_by_profile
            )
            if getattr(duplicate_row, "id", None):
                db.session.delete(duplicate_row)
            else:
                db.session.expunge(duplicate_row)


def _populate_admin_user_form(form: AdminCreateUserForm, user: Optional[User] = None):
    try:
        from ..models import SiteConfig

        cfg = SiteConfig.get()
        sets = list(cfg.rolling_quote_sets.keys()) if cfg and cfg.rolling_quote_sets else list(SiteConfig.DEFAULT_QUOTE_SETS.keys())
        form.quote_set.choices = [("", "(use site default)")] + [(s, s.capitalize()) for s in sets]
        interval_default = getattr(cfg, "rolling_quote_interval_default", 20)
    except Exception:
        form.quote_set.choices = [("", "(use site default)")]
        interval_default = 20

    active_choices = _available_department_choices(include_codes=get_user_departments(user) if user is not None else None)
    form.department.choices = list(active_choices)
    form.watched_departments.choices = list(active_choices)
    form.notification_departments.choices = list(active_choices)

    allowed_depts = []
    if user is not None:
        allowed_depts = get_user_departments(user)
    else:
        seeded_dept = (getattr(form.department, "data", None) or "A")
        allowed_depts = [str(seeded_dept).strip().upper()]
    posted_primary = str(getattr(form.department, "data", "") or "").strip().upper()
    posted_preferred = str(
        getattr(form.preferred_start_department, "data", "") or ""
    ).strip().upper()
    if posted_primary:
        allowed_depts.append(posted_primary)
    if posted_preferred:
        allowed_depts.append(posted_preferred)
    available_codes = set(_available_department_codes(include_codes=allowed_depts))
    allowed_depts = [dept for dept in allowed_depts if dept in available_codes]
    allowed_depts = list(dict.fromkeys(allowed_depts))
    preferred_choices = [("", "Use active department")] + [(dept, dept) for dept in allowed_depts]
    if len(preferred_choices) == 1:
        preferred_choices.extend((dept, label) for dept, label in active_choices if dept not in allowed_depts)
    form.preferred_start_department.choices = preferred_choices
    form.quote_interval.choices = [(i, f"{i} seconds") for i in range(15, 61, 5)]

    backup_users = []
    try:
        backup_users = User.query.filter_by(is_active=True).order_by(User.email.asc()).all()
    except Exception:
        backup_users = []
    selected_backup_id = getattr(user, "backup_approver_user_id", None) if user is not None else None
    if selected_backup_id and not any(candidate.id == selected_backup_id for candidate in backup_users):
        selected_backup = db.session.get(User, selected_backup_id)
        if selected_backup is not None:
            backup_users.append(selected_backup)
    backup_choices = [(0, "No backup approver")]
    for candidate in backup_users:
        if user is not None and candidate.id == user.id:
            continue
        label_parts = [candidate.email]
        if getattr(candidate, "name", None):
            label_parts.append(candidate.name)
        if getattr(candidate, "department", None):
            label_parts.append(f"Dept {candidate.department}")
        backup_choices.append((candidate.id, " · ".join(label_parts)))
    form.backup_approver_user_id.choices = backup_choices

    if flask_request.method == "GET":
        form.quote_interval.data = getattr(user, "quote_interval", None) or interval_default
        form.workflow_role_profile.data = getattr(user, "workflow_role_profile", None) or "member"
        form.preferred_start_page.data = getattr(user, "preferred_start_page", None) or "dashboard"
        form.preferred_start_department.data = getattr(user, "preferred_start_department", None) or ""
        form.watched_departments.data = list(getattr(user, "watched_departments", []) or [])
        form.notification_departments.data = list(
            getattr(user, "notification_departments", []) or []
        )
        form.backup_approver_user_id.data = (
            getattr(user, "backup_approver_user_id", None) or 0
        )


def _apply_admin_user_settings(user: User, form: AdminCreateUserForm):
    user.quote_set = form.quote_set.data or None
    user.quotes_enabled = bool(form.quotes_enabled.data)
    try:
        user.daily_nudge_limit = int(form.daily_nudge_limit.data or 1)
    except Exception:
        user.daily_nudge_limit = 1
    try:
        user.quote_interval = int(form.quote_interval.data or 0) or None
    except Exception:
        user.quote_interval = None
    user.workflow_role_profile = form.workflow_role_profile.data or "member"
    user.preferred_start_page = form.preferred_start_page.data or "dashboard"
    preferred_dept = (form.preferred_start_department.data or "").strip().upper()
    user.preferred_start_department = preferred_dept or None
    watched = [str(dept or "").strip().upper() for dept in (form.watched_departments.data or []) if str(dept or "").strip()]
    user.watched_departments = watched
    routed = [
        str(dept or "").strip().upper()
        for dept in (form.notification_departments.data or [])
        if str(dept or "").strip()
    ]
    user.notification_departments = routed
    backup_user_id = getattr(form, "backup_approver_user_id", None)
    try:
        selected_backup_id = int(backup_user_id.data or 0) if backup_user_id else 0
    except Exception:
        selected_backup_id = 0
    if selected_backup_id and getattr(user, "id", None) and selected_backup_id == user.id:
        selected_backup_id = 0
    user.backup_approver_user_id = selected_backup_id or None


@admin_bp.route("/users")
@login_required

def list_users():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    tenant_id = flask_request.args.get("tenant_id")
    q = (flask_request.args.get("q") or "").strip()
    # admin user list should not be limited by the active tenant scope; we
    # intentionally bypass the ORM loader criteria so the dropdown below can
    # filter manually across all tenants.
    query = User.query.execution_options(skip_tenant_scope=True)

    if tenant_id:
        try:
            tid = int(tenant_id)
            query = query.filter_by(tenant_id=tid)
        except Exception:
            pass

    if q:
        # simple email search; may expand later
        query = query.filter(User.email.ilike(f"%{q}%"))

    users = query.order_by(User.email).all()
    tenants = Tenant.query.order_by(Tenant.name).all()
    now = datetime.utcnow()
    expiring_loans = 0
    multi_dept_users = 0
    for user in users:
        active_assignments = [assignment for assignment in (getattr(user, "departments", []) or []) if getattr(assignment, "is_active_assignment", True)]
        if active_assignments:
            multi_dept_users += 1
        if any(
            getattr(assignment, "expires_at", None)
            and now <= getattr(assignment, "expires_at", None) <= now + timedelta(days=3)
            for assignment in active_assignments
        ):
            expiring_loans += 1
    return render_template(
        "admin_users.html",
        users=users,
        tenants=tenants,
        selected_tenant=int(tenant_id) if tenant_id and tenant_id.isdigit() else None,
        q=q,
        user_stats={
            "total": len(users),
            "inactive": len([u for u in users if not getattr(u, "is_active", False)]),
            "multi_dept": multi_dept_users,
            "expiring_loans": expiring_loans,
        },
    )


@admin_bp.route("/users/new", methods=["GET", "POST"])
@login_required

def create_user():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = AdminCreateUserForm()
    _populate_admin_user_form(form)

    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        name = form.name.data.strip() if form.name.data else None
        dept = form.department.data
        pw = form.password.data or "password123"
        is_active = bool(form.is_active.data)
        is_admin = (getattr(form, "role", None) and form.role.data == "admin") or bool(
            form.is_admin.data
        )
        department_override = bool(getattr(form, "department_override", None) and form.department_override.data)

        existing = User.query.filter_by(email=email).first()
        if existing:
            existing.name = name or existing.name
            existing.department = dept
            existing.department_override = department_override
            if form.password.data:
                existing.password_hash = generate_password_hash(
                    pw, method="pbkdf2:sha256"
                )
            existing.is_active = is_active
            existing.is_admin = is_admin
            _apply_admin_user_settings(existing, form)
            _sync_user_workflow_profile(existing)
            db.session.commit()
            ensure_user_tenant_membership(existing)
            flash(f"Updated user {email}.", "success")
            return redirect(url_for("admin.list_users"))

        u = User(
            email=email,
            name=name,
            department=dept,
            department_override=department_override,
            password_hash=generate_password_hash(pw, method="pbkdf2:sha256"),
            is_active=is_active,
            is_admin=is_admin,
        )
        _apply_admin_user_settings(u, form)
        db.session.add(u)
        db.session.commit()
        _sync_user_workflow_profile(u)
        _dedupe_department_editor_rows(u)
        db.session.commit()
        ensure_user_tenant_membership(u)
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
    form.password.data = None
    _populate_admin_user_form(form, u)

    if form.validate_on_submit():
        u.email = form.email.data.strip().lower()
        u.name = form.name.data.strip() if form.name.data else None
        u.department = form.department.data
        u.department_override = bool(
            getattr(form, "department_override", None) and form.department_override.data
        )
        if form.password.data:
            u.password_hash = generate_password_hash(
                form.password.data, method="pbkdf2:sha256"
            )
        u.is_active = bool(form.is_active.data)
        u.is_admin = (
            getattr(form, "role", None) and form.role.data == "admin"
        ) or bool(form.is_admin.data)
        _apply_admin_user_settings(u, form)
        db.session.commit()
        _sync_user_workflow_profile(u)
        _dedupe_department_editor_rows(u)
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
    for covered_user in User.query.filter_by(backup_approver_user_id=u.id).all():
        covered_user.backup_approver_user_id = None
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
    choices = _available_department_codes(include_codes=get_user_departments(u))
    department_meta = _department_metadata_map(include_codes=choices)

    if flask_request.method == "POST":
        selected = flask_request.form.getlist("departments") or []
        selected = [s.strip().upper() for s in selected if s and s.strip()]
        now = datetime.utcnow()
        overlap_warnings = []

        existing = {ud.department: ud for ud in getattr(u, "departments", [])}
        for dept_code, ud in list(existing.items()):
            if dept_code not in selected:
                try:
                    db.session.delete(ud)
                except Exception:
                    db.session.rollback()

        for dept in selected:
            if dept == getattr(u, "department", None):
                continue
            assignment_kind = (flask_request.form.get(f"assignment_kind_{dept}") or "shared").strip().lower()
            if assignment_kind not in {"shared", "temporary"}:
                assignment_kind = "shared"
            note = (flask_request.form.get(f"assignment_note_{dept}") or "").strip() or None
            handoff_doc_url = (flask_request.form.get(f"assignment_handoff_doc_url_{dept}") or "").strip() or None
            handoff_checklist = [
                line.strip()
                for line in (flask_request.form.get(f"assignment_handoff_checklist_{dept}") or "").splitlines()
                if line.strip()
            ]
            template = department_meta.get(dept)
            if not handoff_doc_url and template is not None:
                handoff_doc_url = getattr(template, "handoff_template_doc_url", None)
            if not handoff_checklist and template is not None:
                handoff_checklist = list(getattr(template, "handoff_template_checklist", []) or [])
            expires_at = None
            raw_expires = flask_request.form.get(f"assignment_expires_at_{dept}")
            if raw_expires:
                try:
                    expires_at = _parse_datetime_local(raw_expires)
                except ValueError as exc:
                    flash(f"{dept}: {exc}", "warning")
                    return redirect(url_for("admin.manage_user_departments", user_id=u.id))

            row = existing.get(dept)
            if not row:
                row = UserDepartment(user_id=u.id, department=dept)
                db.session.add(row)
            starts_at = getattr(row, "created_at", None) or now
            row.assignment_kind = assignment_kind
            row.note = note
            row.handoff_doc_url = handoff_doc_url
            row.handoff_checklist = handoff_checklist
            row.expires_at = expires_at
            if assignment_kind == "temporary" and expires_at:
                conflicts = _temporary_assignment_conflicts(
                    u,
                    starts_at,
                    expires_at,
                    exclude_assignment_id=getattr(row, "id", None),
                )
                if conflicts:
                    overlap_warnings.append(
                        f"Dept {dept} overlaps with {_format_assignment_conflict_message(conflicts)}"
                    )

        try:
            _sync_user_workflow_profile(u)
            _dedupe_department_editor_rows(u)
            db.session.commit()
            flash("Updated department assignments.", "success")
            for warning in overlap_warnings:
                flash(f"Coverage warning: {warning}", "warning")
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            flash("Failed to save assignments.", "danger")

        return redirect(url_for("admin.list_users"))

    assigned_rows = {
        ud.department: ud for ud in getattr(u, "departments", [])
    }
    assigned = [dept for dept, row in assigned_rows.items() if getattr(row, "is_active_assignment", True)]
    overlap_map = {}
    for dept, row in assigned_rows.items():
        if str(getattr(row, "assignment_kind", "shared") or "shared").strip().lower() != "temporary":
            continue
        starts_at = getattr(row, "created_at", None)
        ends_at = getattr(row, "expires_at", None)
        conflicts = _temporary_assignment_conflicts(
            u,
            starts_at,
            ends_at,
            exclude_assignment_id=getattr(row, "id", None),
        )
        if conflicts:
            overlap_map[dept] = conflicts
    return render_template(
        "admin_user_departments.html",
        user=u,
        choices=choices,
        department_meta=department_meta,
        assigned=assigned,
        assigned_rows=assigned_rows,
        overlap_map=overlap_map,
    )


@admin_bp.route("/users/bulk_update", methods=["POST"])
@login_required
def bulk_update_users():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    raw_ids = flask_request.form.getlist("user_ids")
    user_ids = [int(value) for value in raw_ids if str(value).isdigit()]
    if not user_ids:
        flash("Select at least one user first.", "warning")
        return redirect(url_for("admin.list_users"))

    action = (flask_request.form.get("bulk_action") or "").strip().lower()
    users = User.query.filter(User.id.in_(user_ids)).all()
    if not users:
        flash("No matching users found.", "warning")
        return redirect(url_for("admin.list_users"))

    changed = 0
    target_department = (flask_request.form.get("bulk_department") or "").strip().upper()
    target_profile = (flask_request.form.get("bulk_role_profile") or "member").strip().lower() or "member"
    for user in users:
        if action == "activate":
            user.is_active = True
            changed += 1
        elif action == "deactivate":
            if current_user.id == user.id:
                continue
            user.is_active = False
            changed += 1
        elif action == "set_primary_department" and target_department in set(_available_department_codes(include_codes=[target_department])):
            user.department = target_department
            if getattr(user, "preferred_start_department", None) and user.preferred_start_department not in set(get_user_departments(user)):
                user.preferred_start_department = target_department
            _sync_user_workflow_profile(user)
            _dedupe_department_editor_rows(user)
            changed += 1
        elif action == "apply_role_profile":
            user.workflow_role_profile = target_profile
            _sync_user_workflow_profile(user)
            _dedupe_department_editor_rows(user)
            changed += 1

    db.session.commit()
    flash(f"Updated {changed} user{'s' if changed != 1 else ''}.", "success")
    return redirect(url_for("admin.list_users"))


@admin_bp.route("/users/coverage")
@login_required
def coverage_calendar():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    # early parse filters since ICS export should respect them too
    saved_filters = session.get("admin_coverage_filters") or {}
    if flask_request.args.get("reset"):
        session.pop("admin_coverage_filters", None)
        saved_filters = {}

    raw_dept = flask_request.args.get("dept")
    raw_days = flask_request.args.get("days")
    raw_query = flask_request.args.get("q")
    if raw_dept is None:
        raw_dept = saved_filters.get("dept", "")
    if raw_days is None:
        raw_days = saved_filters.get("days", 14)
    if raw_query is None:
        raw_query = saved_filters.get("q", "")

    dept_filter = str(raw_dept or "").strip().upper()
    available_codes = _available_department_codes()
    if dept_filter not in {"", *available_codes}:
        dept_filter = ""

    try:
        horizon_days = int(raw_days or 14)
    except Exception:
        horizon_days = 14
    if horizon_days not in {7, 14, 30}:
        horizon_days = 14

    coverage_query = str(raw_query or "").strip()

    session["admin_coverage_filters"] = {
        "dept": dept_filter,
        "days": horizon_days,
        "q": coverage_query,
    }

    now = datetime.utcnow()
    horizon_end = now + timedelta(days=horizon_days)
    department_meta = _department_metadata_map(include_codes=[dept_filter] if dept_filter else None)
    all_loans = (
        UserDepartment.query.join(User, User.id == UserDepartment.user_id)
        .filter(UserDepartment.assignment_kind == "temporary")
        .filter(UserDepartment.expires_at.isnot(None))
        .filter(User.is_active.is_(True))
        .order_by(UserDepartment.expires_at.asc(), User.email.asc())
        .all()
    )

    loan_entries = []
    for assignment in all_loans:
        dept_code = (getattr(assignment, "department", None) or "").strip().upper()
        if dept_filter and dept_code != dept_filter:
            continue
        starts_at = getattr(assignment, "created_at", None) or now
        ends_at = getattr(assignment, "expires_at", None)
        if not ends_at or ends_at < now:
            continue
        if starts_at > horizon_end:
            continue
        loan_entries.append(
            {
                "assignment": assignment,
                "user": getattr(assignment, "user", None),
                "department": dept_code,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "note": getattr(assignment, "note", None),
                "handoff_doc_url": getattr(assignment, "handoff_doc_url", None),
                "handoff_checklist": list(getattr(assignment, "handoff_checklist", []) or []),
                "backup_approver": getattr(getattr(assignment, "user", None), "backup_approver", None),
            }
        )

    loan_entries = _coverage_entry_conflicts(loan_entries)
    if coverage_query:
        loan_entries = [entry for entry in loan_entries if _coverage_entry_matches_query(entry, coverage_query, department_meta)]

    # if client requested an iCalendar export, generate and return it now
    if flask_request.args.get("format") == "ics":
        # assemble VCALENDAR text
        now = datetime.utcnow()
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//ProcessManagementPrototype//EN",
        ]
        for entry in loan_entries:
            uid = str(uuid.uuid4())
            dtstart = entry["starts_at"].strftime("%Y%m%dT%H%M%SZ")
            dtend = entry["ends_at"].strftime("%Y%m%dT%H%M%SZ")
            summary = f"Loan: {entry['user'].email} ({entry['department']})"
            description_lines = []
            if entry.get("note"):
                description_lines.append(entry.get("note"))
            if entry.get("handoff_doc_url"):
                description_lines.append(f"Handoff doc: {entry.get('handoff_doc_url')}")
            if entry.get("handoff_checklist"):
                description_lines.append("Checklist:")
                description_lines.extend(f"- {item}" for item in entry.get("handoff_checklist") or [])
            desc = "\\n".join(description_lines)
            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART:{dtstart}",
                f"DTEND:{dtend}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{desc}",
                "END:VEVENT",
            ])
        lines.append("END:VCALENDAR")
        ics_text = "\r\n".join(lines)
        return Response(
            ics_text,
            mimetype="text/calendar",
            headers={"Content-Disposition": "attachment; filename=coverage.ics"},
        )

    calendar_days = []
    for offset in range(horizon_days):
        day_start = (now + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        entries = [
            entry
            for entry in loan_entries
            if entry["starts_at"] < day_end and entry["ends_at"] >= day_start
        ]
        calendar_days.append(
            {
                "date": day_start,
                "entries": entries,
            }
        )

    backup_pairs = []
    for user in User.query.filter(User.backup_approver_user_id.isnot(None), User.is_active.is_(True)).order_by(User.department.asc(), User.email.asc()).all():
        departments = [dept for dept in get_user_departments(user) if dept in set(_available_department_codes(include_codes=get_user_departments(user)))]
        if dept_filter and dept_filter not in departments:
            continue
        backup_pairs.append(
            {
                "user": user,
                "backup": getattr(user, "backup_approver", None),
                "departments": departments,
                "notification_departments": list(getattr(user, "notification_departments", []) or []),
            }
        )
    if coverage_query:
        backup_pairs = [pair for pair in backup_pairs if _coverage_pair_matches_query(pair, coverage_query, department_meta)]

    active_loans = [
        entry for entry in loan_entries if entry["starts_at"] <= now <= entry["ends_at"]
    ]
    ending_soon = [
        entry for entry in loan_entries if now <= entry["ends_at"] <= now + timedelta(days=3)
    ]
    conflicting_loans = [entry for entry in loan_entries if entry.get("has_conflict")]

    return render_template(
        "admin_user_coverage.html",
        dept_filter=dept_filter,
        horizon_days=horizon_days,
        loan_entries=loan_entries,
        calendar_days=calendar_days,
        backup_pairs=backup_pairs,
        coverage_stats={
            "active": len(active_loans),
            "ending_soon": len(ending_soon),
            "backup_pairs": len(backup_pairs),
            "conflicts": len(conflicting_loans),
        },
        department_choices=_available_department_choices(include_codes=[dept_filter] if dept_filter else None),
        coverage_query=coverage_query,
        filters_saved=bool(session.get("admin_coverage_filters")),
        now=now,
    )


@admin_bp.route("/users/<int:user_id>/impersonate", methods=["POST"])
@login_required

def impersonate_user(user_id: int):
    if not current_app.config.get("ALLOW_IMPERSONATION"):
        flash("Impersonation feature is disabled.", "danger")
        return redirect(url_for("requests.dashboard"))

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
    session["impersonate_admin_id"] = current_user.id
    session["impersonate_dept"] = target.department
    session["impersonate_started_at"] = datetime.utcnow().isoformat()

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
    if not current_app.config.get("ALLOW_IMPERSONATION"):
        flash("Impersonation feature is disabled.", "danger")
        return redirect(url_for("requests.dashboard"))

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


@admin_bp.route("/impersonate/stop", methods=["GET","POST"])
@login_required

def stop_impersonation():
    # allow GET so users who manually visit the URL (e.g. via bookmark)
    if not current_app.config.get("ALLOW_IMPERSONATION"):
        # nothing to stop; treat as harmless redirect
        flash("Impersonation feature is disabled.", "danger")
        return redirect(url_for("requests.dashboard"))
    # are not greeted with Method Not Allowed.  We simply redirect back to the
    # dashboard with a notice, mirroring the POST behaviour below.

    # handle GET short-circuit: if no impersonation in progress, just
    # redirect; otherwise proceed to clear the session below. This keeps
    # behaviour consistent irrespective of verb.
    admin_id = session.get("impersonate_admin_id")
    if not admin_id:
        flash("Not currently impersonating.", "warning")
        return redirect(url_for("requests.dashboard"))

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

    session.pop("impersonate_admin_id", None)
    session.pop("impersonate_dept", None)
    session.pop("impersonate_started_at", None)
    flash("Stopped acting-as; returned to your normal admin session.", "success")
    return redirect(url_for("admin.list_users"))


@admin_bp.route("/set_self_admin", methods=["POST"])
@login_required

def set_self_admin():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))
    if not current_app.config.get("ALLOW_SELF_ADMIN"):
        flash("Self-admin feature is not enabled on this instance.", "danger")
        return redirect(flask_request.referrer or url_for("requests.dashboard"))

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


@admin_bp.route("/assign_sso", methods=["GET", "POST"])
@login_required

def assign_sso():
    if not _is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("requests.dashboard"))

    form = SSOAssignForm()
    if form.validate_on_submit():
        dept = (form.department.data or "").strip().upper()
        raw = form.emails.data or ""
        parts = []
        for line in raw.splitlines():
            for token in line.split(","):
                token = token.strip().lower()
                if token:
                    parts.append(token)

        skipped = []
        updated = []
        for em in parts:
            u = User.query.filter_by(email=em).first()
            if not u:
                skipped.append((em, "missing"))
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
        seen = set()
        for line in raw.splitlines():
            for token in line.split(","):
                token = token.strip().lower()
                if token and token not in seen:
                    parts.append(token)
                    seen.add(token)

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
                ud = UserDepartment(user_id=u.id, department=dept, assignment_kind="shared")
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
            submitted_count=len(parts),
        )

    return render_template("admin_bulk_assign_departments.html", form=form)
