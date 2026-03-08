from datetime import datetime

from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    session,
    request as flask_request,
    current_app,
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
)
from ..services.tenant_context import ensure_user_tenant_membership
from .utils import _is_admin_user


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
    return render_template(
        "admin_users.html",
        users=users,
        tenants=tenants,
        selected_tenant=int(tenant_id) if tenant_id and tenant_id.isdigit() else None,
        q=q,
    )


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
            ensure_user_tenant_membership(existing)
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
    choices = ["A", "B", "C"]

    if flask_request.method == "POST":
        selected = flask_request.form.getlist("departments") or []
        selected = [s.strip().upper() for s in selected if s and s.strip()]

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
