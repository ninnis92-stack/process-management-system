from flask import Blueprint, render_template, redirect, url_for, flash, current_app, session
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import User
from .forms import AdminCreateUserForm
from ..models import Request as ReqModel, Artifact, Submission
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
