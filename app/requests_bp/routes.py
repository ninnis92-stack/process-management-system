import os
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from sqlalchemy import or_, and_, func

from flask import (
    Blueprint, render_template, redirect, request, url_for, flash, abort, send_file, current_app, jsonify, Response
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (
    Request as ReqModel,
    Comment,
    AuditLog,
    Artifact,
    Submission,
    Attachment,
    User,
    Notification,
)
from .forms import (
    NewRequestForm,
    CommentForm,
    ArtifactForm,
    TransitionForm,
    ToggleCReviewForm,
    RequestArtifactEditForm,
    DonorOnlyForm,
    AssignmentForm,
)
from .permissions import (
    can_view_request,
    visible_comment_scopes_for_user,
    allowed_comment_scopes_for_user,
)
from .workflow import transition_allowed, owner_for_status, handoff_for_transition
from ..services.verification import VerificationService
from ..notifcations import notify_users, users_in_department
from .. import metrics as metrics_module



requests_bp = Blueprint("requests", __name__, url_prefix="")

# Ephemeral in-process presence tracker: request_id -> { user_id: {"email": str, "dept": str, "ts": float} }
_presence: Dict[int, Dict[int, Dict[str, object]]] = {}


# -------------------------
# Helpers / Permissions
# -------------------------

def _exclude_old_closed(query):
    cutoff = datetime.utcnow() - timedelta(hours=24)
    return query.filter(or_(ReqModel.status != "CLOSED", ReqModel.updated_at >= cutoff))

def _has_part_number_artifact(req: ReqModel) -> bool:
    return any(a.artifact_type == "part_number" for a in req.artifacts)


def can_add_artifact(req: ReqModel, dept: str, artifact_type: str) -> bool:
    # Dept B: allow both if you want (your current code allows both)
    if dept == "B":
        return artifact_type in ("part_number", "instructions")

    # Dept A: allow both
    if dept == "A":
        return artifact_type in ("part_number", "instructions")

    # Dept C: only part_number during review if missing
    if dept == "C":
        if artifact_type != "part_number":
            return False
        if req.status != "PENDING_C_REVIEW":
            return False
        if _has_part_number_artifact(req):
            return False
        return True

    return False


def can_edit_artifact(req: ReqModel, artifact: Artifact, dept: str) -> bool:
    # Allow all departments to edit artifacts (UI will present form to any dept).
    # Specific validation rules (e.g., donor-only edits) are enforced in the route if needed.
    return True


def _log(req: ReqModel, action_type: str, note: Optional[str] = None,
         from_status: Optional[str] = None, to_status: Optional[str] = None,
         actor_type: str = "user") -> None:
    entry = AuditLog(
        request_id=req.id,
        actor_type=actor_type,
        actor_user_id=current_user.id if actor_type == "user" else None,
        actor_label=current_user.email if actor_type == "user" else actor_type,
        action_type=action_type,
        from_status=from_status,
        to_status=to_status,
        note=note,
    )
    db.session.add(entry)


def _users_in_dept(dept: str) -> List[User]:
    return User.query.filter_by(department=dept, is_active=True).all()


def _assignment_choices(dept: str):
    users = _users_in_dept(dept)
    # Do not expose admin accounts as assignable choices to non-admin actors.
    if not getattr(current_user, "is_admin", False):
        users = [u for u in users if not getattr(u, "is_admin", False)]
    return [(-1, "Unassigned")] + [(u.id, (u.name or u.email)) for u in users]


def _require_assigned_user(req: ReqModel):
    """Ensure the current user is the assignee for mutating actions.

    Returns a Flask response (redirect) when the request is unassigned; aborts
    with 403 when assigned to someone else. Returns None when OK.
    """
    # If unassigned: instruct the caller to assign first
    if not req.assigned_to_user_id:
        # If this is an AJAX/XHR caller, return JSON so client JS can handle it.
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "error": "unassigned", "message": "Request must be assigned before performing this action."}), 409
        # For GET requests, avoid redirect loops by returning an error status
        if request.method == 'GET':
            abort(409)
        flash("Request must be assigned before performing this action.", "warning")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    # If assigned to someone else: avoid raw 403 pages for normal form submits —
    # redirect with a helpful message. For AJAX callers return JSON + 403.
    if req.assigned_to_user_id != current_user.id:
        other = User.query.get(req.assigned_to_user_id)
        label = (other.name or other.email) if other else "Another user"
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "error": "assigned_to_other", "assigned_to": label}), 403
        # For GET requests, avoid redirect loops by returning 403
        if request.method == 'GET':
            abort(403)
        flash(f"This request is assigned to {label}.", "warning")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    return None


def _success_response(message: str, req: ReqModel, redirect_endpoint: str = "requests.request_detail"):
    """Return JSON for AJAX callers or flash+redirect for normal requests."""
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for(redirect_endpoint, request_id=req.id))


def _last_status_by_owner_dept(req: ReqModel) -> str:
    """Return the most recent status (to_status) changed by a user in the
    request's current owner department. Falls back to the request's current
    status when no matching audit entry exists.
    """
    entry = (
        AuditLog.query
        .filter_by(request_id=req.id, action_type="status_change")
        .join(User, AuditLog.actor_user)
        .filter(User.department == req.owner_department)
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    if entry and entry.to_status:
        return entry.to_status
    return req.status


def _closed_within_hours(req: ReqModel, hours: int = 48) -> bool:
    """Return True if the request was moved to CLOSED within the last `hours` hours."""
    entry = (
        AuditLog.query
        .filter_by(request_id=req.id, action_type="status_change")
        .filter(AuditLog.to_status == "CLOSED")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    if not entry:
        return False
    return (datetime.utcnow() - entry.created_at) <= timedelta(hours=hours)



# Notification helpers are provided by app/notifcations.py (imported above)


def is_transition_valid_for_request(req: ReqModel, dept: str, from_status: str, to_status: str) -> bool:
    if not transition_allowed(dept, from_status, to_status):
        return False

    # If C review is required: block bypass to final review
    if req.requires_c_review and to_status == "B_FINAL_REVIEW" and from_status in ("NEW_FROM_A", "B_IN_PROGRESS"):
        return False

    # If C review is NOT required: block sending to C (for all depts)
    if (not req.requires_c_review) and to_status == "PENDING_C_REVIEW":
        return False

    return True


# -------------------------
# Routes
# -------------------------

@requests_bp.route("/")
def root():
    return redirect(url_for("requests.dashboard"))


@requests_bp.route("/dashboard")
@login_required
def dashboard():
    # Default to the current user's department. Admins may pass ?as_dept=A|B|C to view other departments.
    dept = current_user.department
    if getattr(current_user, 'is_admin', False):
        as_dept = (request.args.get('as_dept') or '').upper()
        if as_dept in ('A', 'B', 'C'):
            dept = as_dept

    artifact_form = ArtifactForm()

    if dept == "A":
        my_reqs = _exclude_old_closed(ReqModel.query.filter_by(
            created_by_user_id=current_user.id
        )).order_by(ReqModel.updated_at.desc()).all()
        return render_template("dashboard.html", mode="A", requests=my_reqs, now=datetime.utcnow(), artifact_form=artifact_form)

    if dept == "B":
        # Allow filtering by a single status via query param `status`
        status_filter = request.args.get("status")

        # Include requests that are owned by B OR that have been sent to B via a Submission
        sent_to_b_subq = db.session.query(Submission.request_id).filter(Submission.to_department == "B").subquery()
        base_b_raw = ReqModel.query.filter(or_(ReqModel.owner_department == "B", ReqModel.id.in_(sent_to_b_subq)))
        base_b = base_b_raw
        # cutoff for 'closed this week' — start of current week (Monday 00:00 UTC)
        now = datetime.utcnow()
        closed_cutoff = datetime(now.year, now.month, now.day) - timedelta(days=now.weekday())

        # Status bar counts for Dept B (owner_department == "B")
        status_counts = {
            "B_IN_PROGRESS": _exclude_old_closed(base_b.filter(
                ReqModel.status == "B_IN_PROGRESS"
            )).count(),
            "WAITING_ON_A_RESPONSE": _exclude_old_closed(base_b.filter(
                ReqModel.status == "WAITING_ON_A_RESPONSE"
            )).count(),
            "PENDING_C_REVIEW": _exclude_old_closed(base_b.filter(
                ReqModel.status == "PENDING_C_REVIEW"
            )).count(),
            "EXEC_APPROVAL": _exclude_old_closed(base_b.filter(
                ReqModel.status == "EXEC_APPROVAL"
            )).count(),
            "B_FINAL_REVIEW": _exclude_old_closed(base_b.filter(
                ReqModel.status == "B_FINAL_REVIEW"
            )).count(),
            "SENT_TO_A": _exclude_old_closed(base_b.filter(
                ReqModel.status == "SENT_TO_A"
            )).count(),
            # Closed this week (reset every 7 days)
            "CLOSED": base_b.filter(
                ReqModel.status == "CLOSED",
                ReqModel.updated_at >= closed_cutoff,
            ).count(),
        }

        # Semantic status filters for Dept B dashboard
        STATUS_LABELS = {
            "in_progress": "In progress by Department B",
            "method_created": "Method created",
            "part_number_created": "Part number created",
            "under_review_by_department_c": "Under review by Department C",
            "waiting_on_department_a": "Pending review from Department A",
            "under_final_review": "Under final review",
            "request_denied": "Request denied",
            # fallbacks for raw status codes
            "NEW_FROM_A": "New from A",
            "B_IN_PROGRESS": "In progress by Department B",
            "PENDING_C_REVIEW": "Under review by Department C",
            "WAITING_ON_A_RESPONSE": "Pending review from Department A",
            "EXEC_APPROVAL": "Requires executive approval",
            "SENT_TO_A": "Sent to A",
            "All": "All (B)",
            "CLOSED": "Closed this week",
        }

        # Build buckets based on the selected semantic filter, otherwise show default buckets
        if status_filter:
            sf = status_filter
            if sf == "in_progress":
                items = base_b.filter(
                    ReqModel.status == "B_IN_PROGRESS",
                ).order_by(ReqModel.updated_at.desc()).all()
            elif sf == "method_created":
                # Requests with an 'instructions' artifact
                items = base_b.join(Artifact).filter(
                    Artifact.artifact_type == "instructions",
                ).order_by(ReqModel.updated_at.desc()).distinct().all()
            elif sf == "part_number_created":
                # Requests with a part_number artifact that has any part number filled
                items = base_b.join(Artifact).filter(
                    Artifact.artifact_type == "part_number",
                    (Artifact.target_part_number.isnot(None)) | (Artifact.donor_part_number.isnot(None)),
                ).order_by(ReqModel.updated_at.desc()).distinct().all()
            elif sf == "under_review_by_department_c":
                items = base_b.filter(
                    ReqModel.status == "PENDING_C_REVIEW",
                ).order_by(ReqModel.updated_at.desc()).all()
            elif sf == "waiting_on_department_a":
                items = base_b.filter(
                    ReqModel.status == "WAITING_ON_A_RESPONSE",
                ).order_by(ReqModel.updated_at.desc()).all()
            elif sf == "under_final_review":
                items = base_b.filter(
                    ReqModel.status == "B_FINAL_REVIEW",
                ).order_by(ReqModel.updated_at.desc()).all()
            elif sf == "exec_approval":
                items = base_b.filter(
                    ReqModel.status == "EXEC_APPROVAL",
                ).order_by(ReqModel.updated_at.desc()).all()
            elif sf == "request_denied":
                items = base_b.filter(
                    ReqModel.status == "CLOSED",
                ).order_by(ReqModel.updated_at.desc()).all()
            else:
                # fallback: treat as raw status code
                items = base_b.filter(
                    ReqModel.status == status_filter,
                ).order_by(ReqModel.updated_at.desc()).all()

            label = STATUS_LABELS.get(status_filter, status_filter)
            buckets = {label: items}
        else:
            buckets = {
            "New from A": base_b.filter(
                ReqModel.status == "NEW_FROM_A",
            ).order_by(ReqModel.updated_at.desc()).all(),

            "In progress by Department B": base_b.filter(
                ReqModel.status == "B_IN_PROGRESS",
            ).order_by(ReqModel.updated_at.desc()).all(),

            "Pending review from Department A": base_b.filter(
                ReqModel.status == "WAITING_ON_A_RESPONSE",
            ).order_by(ReqModel.updated_at.desc()).all(),

            "Needs changes": base_b.filter(
                ReqModel.status == "C_NEEDS_CHANGES",
            ).order_by(ReqModel.updated_at.desc()).all(),

            "Exec approval required": base_b.filter(
                ReqModel.status == "EXEC_APPROVAL",
            ).order_by(ReqModel.updated_at.desc()).all(),

            "Approved by C": base_b.filter(
                ReqModel.status == "C_APPROVED",
            ).order_by(ReqModel.updated_at.desc()).all(),

            "Final review": base_b.filter(
                ReqModel.status == "B_FINAL_REVIEW",
            ).order_by(ReqModel.updated_at.desc()).all(),

            "Sent to A": base_b.filter(
                ReqModel.status == "SENT_TO_A",
            ).order_by(ReqModel.updated_at.desc()).all(),

            "Under review by Department C": base_b.filter(
                ReqModel.status == "PENDING_C_REVIEW",
            ).order_by(ReqModel.updated_at.desc()).all(),

            "Closed this week": base_b.filter(
                ReqModel.status == "CLOSED",
                ReqModel.updated_at >= closed_cutoff,
            ).order_by(ReqModel.updated_at.desc()).all(),

            "All (B)": base_b.order_by(ReqModel.updated_at.desc()).all(),
        }
        # Annotate each request with the last status set by the current owner dept
        for name, reqs in buckets.items():
            for r in reqs:
                try:
                    r.last_owner_status = _last_status_by_owner_dept(r)
                except Exception:
                    r.last_owner_status = r.status

        return render_template("dashboard.html", mode="B", buckets=buckets, status_counts=status_counts, now=datetime.utcnow(), artifact_form=artifact_form)

    if dept == "C":
        pending = ReqModel.query.filter_by(
            status="PENDING_C_REVIEW"
        ).order_by(ReqModel.updated_at.desc()).all()
        return render_template("dashboard.html", mode="C", requests=pending, now=datetime.utcnow(), artifact_form=artifact_form)

    abort(403)


@requests_bp.route("/search")
@login_required
def search_requests():
    q = (request.args.get("q") or "").strip()
    dept = current_user.department
    base = ReqModel.query

    if dept == "A":
        base = base.filter(ReqModel.created_by_user_id == current_user.id)
    elif dept == "B":
        base = base.filter(ReqModel.owner_department == "B")
    else:
        base = base.filter(ReqModel.status.in_([
            "PENDING_C_REVIEW", "C_NEEDS_CHANGES", "C_APPROVED", "B_FINAL_REVIEW", "SENT_TO_A", "CLOSED"
        ]))

    results = []
    if q:
        # Numeric queries should match request id exactly, but also look for text in other fields
        filters = [
            ReqModel.title.ilike(f"%{q}%"),
            ReqModel.description.ilike(f"%{q}%"),
        ]

        # Search artifacts (part numbers / instructions URL)
        filters.extend([
            Artifact.donor_part_number.ilike(f"%{q}%"),
            Artifact.target_part_number.ilike(f"%{q}%"),
            Artifact.instructions_url.ilike(f"%{q}%"),
        ])

        # Search comments and submissions text
        filters.extend([
            Comment.body.ilike(f"%{q}%"),
            Submission.summary.ilike(f"%{q}%"),
            Submission.details.ilike(f"%{q}%"),
        ])

        qry = base.outerjoin(Artifact, Artifact.request_id == ReqModel.id)
        qry = qry.outerjoin(Comment, Comment.request_id == ReqModel.id)
        qry = qry.outerjoin(Submission, Submission.request_id == ReqModel.id)

        if q.isdigit():
            # include exact id matches as well
            id_filter = ReqModel.id == int(q)
            qry = qry.filter(or_(id_filter, *filters))
        else:
            qry = qry.filter(or_(*filters))

    return render_template('search.html', results=qry.order_by(ReqModel.updated_at.desc()).all(), q=q)


@requests_bp.route('/metrics/ui')
@login_required
def metrics_ui():
    """Simple DB-backed metrics UI: counts per owner department and recent activity."""
    # Accept a `range` parameter: daily, weekly, monthly, yearly (defaults to weekly)
    r = (request.args.get('range') or 'weekly').lower()
    now = datetime.utcnow()
    if r == 'daily':
        cutoff = datetime(now.year, now.month, now.day)
        label = 'Daily (since today 00:00 UTC)'
    elif r == 'monthly':
        cutoff = datetime(now.year, now.month, 1)
        label = 'Monthly (since start of month)'
    elif r == 'yearly':
        cutoff = datetime(now.year, 1, 1)
        label = 'Yearly (since start of year)'
    else:
        # weekly (default): start of current week (Monday 00:00 UTC)
        cutoff = datetime(now.year, now.month, now.day) - timedelta(days=now.weekday())
        label = 'Weekly (since start of week)'

    # Total requests by owner department
    totals = dict(db.session.query(ReqModel.owner_department, func.count(ReqModel.id)).group_by(ReqModel.owner_department).all())

    # Open requests (not CLOSED) by owner dept
    opens = dict(db.session.query(ReqModel.owner_department, func.count(ReqModel.id)).filter(ReqModel.status != 'CLOSED').group_by(ReqModel.owner_department).all())

    # Requests created in the selected window by owner dept
    created_window = dict(db.session.query(ReqModel.owner_department, func.count(ReqModel.id)).filter(ReqModel.created_at >= cutoff).group_by(ReqModel.owner_department).all())

    # Requests closed in the selected window by owner dept
    closed_window = dict(db.session.query(ReqModel.owner_department, func.count(ReqModel.id)).filter(ReqModel.status == 'CLOSED', ReqModel.updated_at >= cutoff).group_by(ReqModel.owner_department).all())

    # Determine which departments the current user may view
    if getattr(current_user, 'is_admin', False):
        depts = ['A', 'B', 'C']
    else:
        depts = [current_user.department]
    metrics = []
    for d in depts:
        metrics.append({
            'dept': d,
            'total': totals.get(d, 0),
            'open': opens.get(d, 0),
            'created_window': created_window.get(d, 0),
            'closed_window': closed_window.get(d, 0),
        })

    return render_template('metrics.html', metrics=metrics, now=now, cutoff=cutoff, range_label=label, range_key=r)
    


@requests_bp.route('/metrics')
def metrics():
    """Prometheus metrics exposition endpoint."""
    try:
        payload, content_type = metrics_module.metrics_output()
        return Response(payload, content_type=content_type)
    except Exception:
        current_app.logger.exception('Failed to generate Prometheus metrics')
        abort(500)


@requests_bp.route('/metrics/json')
def metrics_json():
    """Machine-friendly JSON metrics for external integrations."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=7)

        totals = dict(db.session.query(ReqModel.owner_department, func.count(ReqModel.id)).group_by(ReqModel.owner_department).all())
        opens = dict(db.session.query(ReqModel.owner_department, func.count(ReqModel.id)).filter(ReqModel.status != 'CLOSED').group_by(ReqModel.owner_department).all())
        created_week = dict(db.session.query(ReqModel.owner_department, func.count(ReqModel.id)).filter(ReqModel.created_at >= cutoff).group_by(ReqModel.owner_department).all())
        closed_week = dict(db.session.query(ReqModel.owner_department, func.count(ReqModel.id)).filter(ReqModel.status == 'CLOSED', ReqModel.updated_at >= cutoff).group_by(ReqModel.owner_department).all())

        # Support `range` param for JSON endpoint as well
        r = (request.args.get('range') or 'weekly').lower()
        now = datetime.utcnow()
        if r == 'daily':
            cutoff = datetime(now.year, now.month, now.day)
        elif r == 'monthly':
            cutoff = datetime(now.year, now.month, 1)
        elif r == 'yearly':
            cutoff = datetime(now.year, 1, 1)
        else:
            cutoff = datetime(now.year, now.month, now.day) - timedelta(days=now.weekday())

        created_window = dict(db.session.query(ReqModel.owner_department, func.count(ReqModel.id)).filter(ReqModel.created_at >= cutoff).group_by(ReqModel.owner_department).all())
        closed_window = dict(db.session.query(ReqModel.owner_department, func.count(ReqModel.id)).filter(ReqModel.status == 'CLOSED', ReqModel.updated_at >= cutoff).group_by(ReqModel.owner_department).all())

        payload = {
            'now': now.isoformat() + 'Z',
            'cutoff': cutoff.isoformat() + 'Z',
            'range': r,
            'by_dept': {},
        }
        for d in ('A', 'B', 'C'):
            payload['by_dept'][d] = {
                'total': totals.get(d, 0),
                'open': opens.get(d, 0),
                'created_window': created_window.get(d, 0),
                'closed_window': closed_window.get(d, 0),
            }
        return jsonify(payload)
    except Exception:
        current_app.logger.exception('Failed to render JSON metrics')
        abort(500)
    


@requests_bp.route("/requests/new", methods=["GET", "POST"])
@login_required
def request_new():
    form = NewRequestForm()

    if request.method == "POST":
        ok = form.validate_on_submit()
        print("VALID:", ok)
        print("ERRORS:", form.errors)

    if form.validate_on_submit():
        req = ReqModel(
            title=form.title.data.strip(),
            request_type=form.request_type.data,
            pricebook_status=form.pricebook_status.data,
            description=form.description.data.strip(),
            priority=form.priority.data,
            requires_c_review=False,
            status="NEW_FROM_A",
            owner_department="B",
            submitter_type="user",
            created_by_user_id=current_user.id,
            due_at=form.due_at.data,
        )

        db.session.add(req)
        db.session.flush()  # req.id available

        # Auto-create initial artifact (so you don’t need to "Add Artifact" after submission)
        # Decide artifact_type based on request_type
        rt = (form.request_type.data or "").strip()
        if rt == "part_number":
            artifact_type = "part_number"
        elif rt == "instructions":
            artifact_type = "instructions"
        else:
            # "both" -> pick one type, OR you can create TWO artifacts. For now create part_number by default.
            artifact_type = "part_number"

        instructions_field = getattr(form, "instructions_url", None)
        instructions_url = (instructions_field.data or "").strip() if instructions_field else None

        a = Artifact(
            request_id=req.id,
            instructions_url=instructions_url,
            artifact_type=artifact_type,
            donor_part_number=(getattr(form, "donor_part_number", None).data or "").strip() or None,
            target_part_number=(getattr(form, "target_part_number", None).data or "").strip() or None,
            no_donor_reason=(getattr(form, "no_donor_reason", None).data or "").strip() or None,
            created_by_user_id=current_user.id,
            created_by_department="A",
        )
        db.session.add(a)
        _log(req, "artifact_added", note=f"Initial artifact created at submission: {a.artifact_type}")

        # Notify the owner department that a request was generated
        notify_users(
            users_in_department(req.owner_department),
            title=f"Request generated: #{req.id}",
            body=f"{req.title} — generated by {current_user.email}",
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="request_generated",
            request_id=req.id,
        )

        db.session.commit()
        try:
            # Prometheus: increment created counter and refresh owner gauge
            metrics_module.requests_created_total.labels(dept=req.owner_department).inc()
            metrics_module.update_owner_gauge(db.session, ReqModel)
        except Exception:
            current_app.logger.exception('Failed to update metrics on request creation')

        flash(f"Request #{req.id} submitted successfully.", "success")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    return render_template("request_new.html", form=form)


@requests_bp.route("/requests/<int:request_id>")
@login_required
def request_detail(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)

    # Viewing the request should not be blocked by assignment checks so that
    # Dept C users can inspect B-owned requests that are pending C review
    # and assign them within the UI. Mutating endpoints still enforce
    # assignment via `_require_assigned_user`.

    now = datetime.utcnow()
    next_hint = None
    if current_user.department == "A":
        if req.status == "SENT_TO_A":
            next_hint = "Review the handoff and either request review from Dept B or close it out."
        elif req.status == "CLOSED":
            next_hint = "Closed — you can reopen if something’s off."
    elif current_user.department == "B":
        if req.status == "NEW_FROM_A":
            next_hint = "Pick it up and move to In Progress."
        elif req.status == "B_IN_PROGRESS" and req.requires_c_review:
            next_hint = "Prep for Dept C review — capture a summary and send."
        elif req.status == "B_IN_PROGRESS" and not req.requires_c_review:
            next_hint = "No C review needed — move toward Final Review."
        elif req.status == "PENDING_C_REVIEW":
            next_hint = "Wait for Dept C feedback."
        elif req.status == "WAITING_ON_A_RESPONSE":
            next_hint = "Pending Department A review — follow up if needed and resume when unblocked."
        elif req.status == "B_FINAL_REVIEW":
            next_hint = "Finalize and send to Dept A."
        elif req.status == "EXEC_APPROVAL":
            next_hint = "Awaiting executive approval — follow up and send when cleared."
    elif current_user.department == "C":
        if req.status == "PENDING_C_REVIEW":
            next_hint = "Review and either approve or request changes."

    allowed_scopes = visible_comment_scopes_for_user()
    comments = Comment.query.filter_by(request_id=req.id).order_by(Comment.created_at.asc()).all()
    comments = [c for c in comments if c.visibility_scope in allowed_scopes]

    comment_form = CommentForm()
    comment_form.visibility_scope.choices = [
        (s, s.replace("_", " ").title())
        for s in allowed_comment_scopes_for_user()
    ]

    artifact_form = ArtifactForm()

    transition_form = TransitionForm()
    dept = current_user.department
    # Build status choices per department: A only sees reopen/close, B sees all B-facing states (validation on submit), C stays constrained.
    if dept == "A":
        possible = []
        label_map = {
            "B_IN_PROGRESS": "Request review from Department B",
            "CLOSED": "Close ticket",
        }
        if req.status == "SENT_TO_A":
            for to in ("B_IN_PROGRESS", "CLOSED"):
                if is_transition_valid_for_request(req, dept, req.status, to):
                    possible.append((to, label_map[to]))
        elif req.status == "CLOSED":
            # Allow Dept A to reopen only within 48 hours of closure.
            if _closed_within_hours(req, hours=48) and is_transition_valid_for_request(req, dept, req.status, "B_IN_PROGRESS"):
                possible.append(("B_IN_PROGRESS", label_map["B_IN_PROGRESS"]))
        transition_form.to_status.choices = possible
    elif dept == "B":
        possible = []
        for to in ("B_IN_PROGRESS", "WAITING_ON_A_RESPONSE", "PENDING_C_REVIEW", "C_APPROVED", "C_NEEDS_CHANGES",
                   "B_FINAL_REVIEW", "EXEC_APPROVAL", "SENT_TO_A", "CLOSED"):
            if to == "WAITING_ON_A_RESPONSE":
                label = "Pending review from Department A"
            elif to == "B_IN_PROGRESS":
                label = "In progress by Department B"
            elif to == "PENDING_C_REVIEW":
                label = "Under review by Department C"
            elif to == "EXEC_APPROVAL":
                label = "Requires executive approval"
            else:
                label = to.replace("_", " ").title()
            possible.append((to, label))
        transition_form.to_status.choices = possible
        transition_form.requires_c_review.data = req.requires_c_review
    else:
        possible = []
        for to in ("C_APPROVED", "C_NEEDS_CHANGES"):
            if is_transition_valid_for_request(req, dept, req.status, to):
                possible.append((to, to.replace("_", " ").title()))
        transition_form.to_status.choices = possible

    toggle_form = ToggleCReviewForm()
    request_edit_form = RequestArtifactEditForm()
    donor_form = DonorOnlyForm()

    assignment_form = None
    # Dept B may assign requests they own. Dept C should be able to assign
    # requests that are currently awaiting C review so they can claim work.
    # Dept A should be able to assign requests that are currently owned by Dept A.
    if current_user.department == "B" and req.owner_department == "B":
        assignment_form = AssignmentForm()
        assignment_form.assignee.choices = _assignment_choices(current_user.department)
        assignment_form.assignee.data = req.assigned_to_user_id or -1
    elif current_user.department == "C" and req.status == "PENDING_C_REVIEW" and req.requires_c_review:
        # Show an assignment UI scoped to Dept C users so they can take ownership
        assignment_form = AssignmentForm()
        assignment_form.assignee.choices = _assignment_choices(current_user.department)
        assignment_form.assignee.data = req.assigned_to_user_id or -1
    elif current_user.department == "A" and req.owner_department == "A":
        # Dept A assignment UI
        assignment_form = AssignmentForm()
        assignment_form.assignee.choices = _assignment_choices(current_user.department)
        assignment_form.assignee.data = req.assigned_to_user_id or -1

    submissions = Submission.query.filter_by(request_id=req.id).order_by(Submission.created_at.asc()).all()
    audit = AuditLog.query.filter_by(request_id=req.id).order_by(AuditLog.created_at.asc()).all()

    has_part_number = any(a.artifact_type == "part_number" for a in req.artifacts)
    has_instructions = any(a.artifact_type == "instructions" for a in req.artifacts)

    return render_template(
        "request_detail.html",
        req=req,
        comments=comments,
        submissions=submissions,
        audit=audit,
        comment_form=comment_form,
        artifact_form=artifact_form,
        transition_form=transition_form,
        toggle_form=toggle_form,
        request_edit_form=request_edit_form,
        donor_form=donor_form,
        assignment_form=assignment_form,
        has_part_number=has_part_number,
        has_instructions=has_instructions,
        next_hint=next_hint,
        now=now,
        assigned_user=req.assigned_to_user,
        handoff_targets=[t for t, _ in possible if handoff_for_transition(req.status, t)],
    )


@requests_bp.route("/requests/<int:request_id>/assign_self", methods=["POST"])
@login_required
def assign_self(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if current_user.department not in ("A", "B", "C"):
        abort(403)
    if not can_view_request(req):
        abort(403)

    if req.status == "CLOSED":
        flash("Cannot assign a closed request.", "warning")
        return redirect(url_for("requests.request_detail", request_id=request_id))

    if req.assigned_to_user_id and req.assigned_to_user_id != current_user.id:
        flash("This request is already assigned.", "warning")
        return redirect(url_for("requests.request_detail", request_id=request_id))

    req.assigned_to_user_id = current_user.id

    _log(req, "assignment_changed", note=f"Assigned to {current_user.email}")

    # Notify the original submitter if they are an internal user
    if req.created_by_user_id:
        assignee_label = current_user.name or current_user.email
        db.session.add(Notification(
            user_id=req.created_by_user_id,
            request_id=req.id,
            type="assignment",
            title="Assignment update",
            body=f"{assignee_label} is assigned to your request.",
            url=url_for("requests.request_detail", request_id=req.id),
        ))
    elif req.submitter_type == "guest" and req.guest_email:
        # For guests, leave a public comment so it surfaces on their external view
        assignee_label = current_user.name or current_user.email
        c = Comment(
            request_id=req.id,
            author_type="user",
            author_user_id=current_user.id,
            visibility_scope="public",
            body=f"Assignment update: {assignee_label} is assigned to your request.",
        )
        db.session.add(c)

    db.session.commit()
    try:
        # Prometheus: assignment made
        metrics_module.assignment_changes_total.labels(dept=current_user.department, action='assigned').inc()
        metrics_module.update_owner_gauge(db.session, ReqModel)
    except Exception:
        current_app.logger.exception('Failed to update metrics on assignment')

    flash("Assigned to you.", "success")
    return redirect(url_for("requests.request_detail", request_id=request_id))


def _clean_presence():
    cutoff = time.time() - 70
    for rid in list(_presence.keys()):
        _presence[rid] = {uid: info for uid, info in _presence[rid].items() if info.get("ts", 0) >= cutoff}
        if not _presence[rid]:
            _presence.pop(rid, None)


@requests_bp.route("/requests/<int:request_id>/presence", methods=["GET", "POST"])
@login_required
def request_presence(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)

    _clean_presence()
    if request.method == "POST":
        bucket = _presence.setdefault(request_id, {})
        bucket[current_user.id] = {
            "email": current_user.email,
            "dept": current_user.department,
            "ts": time.time(),
        }
        return jsonify({"ok": True})

    # GET
    viewers = _presence.get(request_id, {})
    same_dept = [
        {"email": info["email"], "dept": info["dept"]}
        for uid, info in viewers.items()
        if info.get("dept") == current_user.department and uid != current_user.id
    ]
    return jsonify({"viewers": same_dept})



@requests_bp.route("/artifacts/<int:artifact_id>/request_edit", methods=["POST"])
@login_required
def request_artifact_edit(artifact_id: int):
    """Mark an artifact as edit-requested and notify the artifact owner department.

    Dept B/C may request Dept A to edit donor/target values; this records the request,
    logs an audit entry, and notifies the owning department for visibility.
    """
    a = Artifact.query.get_or_404(artifact_id)
    req = a.request
    if not can_view_request(req):
        abort(403)

    rv = _require_assigned_user(req)
    if rv:
        return rv

    rv = _require_assigned_user(req)
    if rv:
        return rv

    # Only internal departments should request edits
    if current_user.department not in ("A", "B", "C"):
        abort(403)

    form = RequestArtifactEditForm()
    if not form.validate_on_submit():
        flash("Edit request failed validation.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    note = (form.note.data or "").strip() or None
    a.edit_requested = True
    a.edit_requested_note = note

    # Audit log for visibility
    _log(req, "edit_requested", note=f"Dept {current_user.department} requested edit: {note}")

    # Determine which department should be notified: prefer the artifact creator dept (if present)
    target_dept = a.created_by_department or req.owner_department
    try:
        notify_users(
            users_in_department(target_dept),
            title=f"Edit requested on Request #{req.id}",
            body=(f"{current_user.department} requested an artifact edit: {note}" if note else f"{current_user.department} requested an artifact edit."),
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="edit_requested",
            request_id=req.id,
        )
    except Exception:
        current_app.logger.exception("Failed to notify users about edit request")

    db.session.commit()
    flash("Edit request sent.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))



@requests_bp.route("/requests/<int:request_id>/verification-placeholder", methods=["POST"])
@login_required
def store_verification_placeholder(request_id: int):
    # Temporary logging endpoint; once integration is available, this should look up the method/part in the source system before persisting.
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)

    if current_user.department != "B":
        abort(403)

    rv = _require_assigned_user(req)
    if rv:
        return rv

    created_method = (request.form.get("created_method") or "").strip()
    created_part = (request.form.get("created_part_number") or "").strip()
    note = (request.form.get("note") or "").strip()

    if not created_method and not created_part:
        flash("Please enter a method or part number to log.", "warning")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    note_lines = []
    if created_method:
        note_lines.append(f"Method: {created_method}")
    if created_part:
        note_lines.append(f"Part: {created_part}")
    if note:
        note_lines.append(f"Note: {note}")

    # Attempt to verify using configured external services (non-blocking)
    verifier = VerificationService()
    ver_results = []
    if created_method:
        vm = verifier.verify_method(created_method)
        ver_results.append(("method", created_method, vm))
        if vm.get("ok") is True:
            note_lines.append(f"Method verification: OK")
        elif vm.get("ok") is False:
            note_lines.append(f"Method verification: FAILED ({vm.get('reason') or vm.get('error')})")
        else:
            note_lines.append("Method verification: not configured")

    if created_part:
        vp = verifier.verify_part_number(created_part)
        ver_results.append(("part", created_part, vp))
        if vp.get("ok") is True:
            note_lines.append(f"Part verification: OK")
        elif vp.get("ok") is False:
            note_lines.append(f"Part verification: FAILED ({vp.get('reason') or vp.get('error')})")
        else:
            note_lines.append("Part verification: not configured")

    _log(req, "verification_placeholder", note="; ".join(note_lines))
    db.session.commit()

    # Provide immediate feedback to the user
    flashes = ["Logged for now."]
    for kind, value, res in ver_results:
        if res.get("ok") is True:
            flashes.append(f"{kind.title()} '{value}' verified OK.")
        elif res.get("ok") is False:
            reason = res.get("reason") or res.get("error") or "unknown"
            flashes.append(f"{kind.title()} '{value}' verification failed: {reason}.")
        else:
            flashes.append(f"{kind.title()} '{value}' verification not configured.")

    for msg in flashes:
        flash(msg, "info")

    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route("/requests/<int:request_id>/comment", methods=["POST"])
@login_required
def add_comment(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)

    form = CommentForm()
    form.visibility_scope.choices = [(s, s) for s in allowed_comment_scopes_for_user()]

    if not form.validate_on_submit():
        flash("Comment failed validation.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    c = Comment(
        request_id=req.id,
        author_type="user",
        author_user_id=current_user.id,
        visibility_scope=form.visibility_scope.data,
        body=form.body.data.strip(),
    )
    db.session.add(c)

    # Notify owner dept + creator (exclude actor)
    targets: List[User] = []
    targets.extend(_users_in_dept(req.owner_department))

    if req.created_by_user_id:
        creator = User.query.get(req.created_by_user_id)
        if creator and getattr(creator, "is_active", True):
            targets.append(creator)

    unique = {u.id: u for u in targets}.values()
    unique = [u for u in unique if u.id != current_user.id]

    notify_users(
        unique,
        title=f"New comment on Request #{req.id}",
        body=(c.body[:160] + "…") if len(c.body) > 160 else c.body,
        url=url_for("requests.request_detail", request_id=req.id),
        ntype="comment",
        request_id=req.id,
    )

    _log(req, "comment_added", note=f"Comment added ({c.visibility_scope}).")
    db.session.commit()

    flash("Comment added.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route("/artifacts/<int:artifact_id>/set_donor", methods=["POST"])
@login_required
def set_artifact_donor(artifact_id: int):
    a = Artifact.query.get_or_404(artifact_id)
    req = a.request
    if not can_view_request(req):
        abort(403)
    # Only Dept B may set donor via this quick form
    if current_user.department != "B":
        abort(403)

    rv = _require_assigned_user(req)
    if rv:
        return rv

    donor = (request.form.get("donor_part_number") or "").strip() or None
    a.donor_part_number = donor
    _log(req, "artifact_updated", note=f"Donor updated to: {donor}")
    # Notify owner and Dept C (if applicable)
    try:
        recipients = list(users_in_department(req.owner_department))
        if req.requires_c_review:
            recipients.extend(users_in_department('C'))
        uniq = {u.id: u for u in recipients}.values()
        notify_users(
            uniq,
            title=f"Donor part number updated on Request #{req.id}",
            body=(f"Donor set: {donor} — by {current_user.email}" if donor else f"Donor cleared by {current_user.email}"),
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="artifact_donor_updated",
            request_id=req.id,
        )
    except Exception:
        current_app.logger.exception("Failed to queue donor notifications")

    db.session.commit()
    return _success_response("Donor part number updated.", req)


@requests_bp.route("/artifacts/<int:artifact_id>/set_target", methods=["POST"])
@login_required
def set_artifact_target(artifact_id: int):
    """Quick setter for a target part number from dashboard; notifies owner dept."""
    a = Artifact.query.get_or_404(artifact_id)
    req = a.request
    if not can_view_request(req):
        abort(403)

    rv = _require_assigned_user(req)
    if rv:
        return rv

    # Allow Dept A/B to quickly set a target from the dashboard
    if current_user.department not in ("A", "B"):
        abort(403)

    target = (request.form.get("target_part_number") or "").strip() or None
    a.target_part_number = target
    _log(req, "artifact_updated", note=f"Target updated to: {target}")

    # Notify users in the owner department that the target was set
    try:
        recipients = list(users_in_department(req.owner_department))
        # If this request requires Dept C review, also notify Dept C users so they can see the part number
        if req.requires_c_review:
            recipients.extend(users_in_department('C'))
        # Deduplicate
        uniq = {u.id: u for u in recipients}.values()
        notify_users(
            uniq,
            title=f"Part number updated on Request #{req.id}",
            body=(f"Target part number set: {target} — by {current_user.email}" if target else f"Target cleared by {current_user.email}"),
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="artifact_target_added",
            request_id=req.id,
        )
    except Exception:
        # notification failures should not block the update
        current_app.logger.exception("Failed to queue notifications for artifact target change")

    db.session.commit()
    return _success_response("Target part number updated.", req)


@requests_bp.route("/artifacts/<int:artifact_id>/edit", methods=["POST"])
@login_required
def edit_artifact(artifact_id: int):
    a = Artifact.query.get_or_404(artifact_id)
    req = a.request
    if not can_view_request(req):
        abort(403)

    # Allow Dept B to update part_number artifacts, and Dept A to perform edits only
    # when an edit was explicitly requested (can_edit_artifact enforces this policy).
    dept = current_user.department
    # Allow any department to edit artifacts
    if dept not in ("A", "B", "C"):
        abort(403)

    if not can_edit_artifact(req, a, dept):
        abort(403)

    form = ArtifactForm()
    if not form.validate_on_submit():
        flash("Artifact edit failed validation.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    # Accept edits from any department. Record the incoming values.
    new_donor = (form.donor_part_number.data or "").strip() or None

    a.donor_part_number = new_donor
    a.target_part_number = (form.target_part_number.data or "").strip() or None
    a.no_donor_reason = (form.no_donor_reason.data or "").strip() or None
    a.instructions_url = (form.instructions_url.data or "").strip() or None

    # clear edit request flag when edited by any department
    a.edit_requested = False

    _log(req, "artifact_edited", note=f"Artifact edited by Dept {dept}: {a.artifact_type}")

    # Notify involved departments (owner and creator) about the change
    try:
        users = []
        # owner department
        if req.owner_department:
            users.extend(users_in_department(req.owner_department))
        # creator department (if different)
        creator_dept = req.created_by_department
        if creator_dept and creator_dept != req.owner_department:
            users.extend(users_in_department(creator_dept))
        # dedupe and exclude the acting user
        uniq = {u.id: u for u in users}.values()
        # If this requires Dept C review, include Dept C users
        if req.requires_c_review:
            users.extend(users_in_department('C'))
            uniq = {u.id: u for u in users}.values()
        recipients = [u for u in uniq if u.id != current_user.id]
        if recipients:
            title = f"Artifact updated on Request #{req.id}"
            body = f"{current_user.email} edited the {a.artifact_type} artifact on Request #{req.id}."
            url = url_for('requests.request_detail', request_id=req.id)
            notify_users(recipients, title=title, body=body, url=url, ntype='artifact_edited', request_id=req.id)
    except Exception:
        current_app.logger.exception('Failed to queue artifact edit notifications')

    db.session.commit()
    return _success_response("Artifact updated.", req)


@requests_bp.route("/requests/<int:request_id>/artifact", methods=["POST"])
@login_required
def add_artifact(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)

    rv = _require_assigned_user(req)
    if rv:
        return rv

    form = ArtifactForm()
    dept = current_user.department

    if not can_add_artifact(req, dept, form.artifact_type.data):
        abort(403)

    if not form.validate_on_submit():
        flash("Artifact failed validation.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    a = Artifact(
        request_id=req.id,
        artifact_type=form.artifact_type.data,
        donor_part_number=(form.donor_part_number.data or "").strip() or None,
        target_part_number=(form.target_part_number.data or "").strip() or None,
        no_donor_reason=(form.no_donor_reason.data or "").strip() or None,
        instructions_url=(form.instructions_url.data or "").strip() or None,
        created_by_user_id=current_user.id,
        created_by_department=current_user.department,
    )
    db.session.add(a)

    _log(req, "artifact_added", note=f"Artifact added: {a.artifact_type}")
    db.session.commit()
    return _success_response("Artifact added.", req)


def _validate_files(files) -> list:
    cfg = current_app.config
    cleaned = []
    if not files:
        return cleaned
    if len(files) > cfg["MAX_FILES_PER_SUBMISSION"]:
        raise ValueError(f"Too many files (max {cfg['MAX_FILES_PER_SUBMISSION']}).")
    for f in files:
        if not f or not f.filename:
            continue
        if f.mimetype not in cfg["ALLOWED_IMAGE_MIMES"]:
            raise ValueError("Only PNG/JPEG/WebP images are allowed.")
        pos = f.stream.tell()
        f.stream.seek(0, os.SEEK_END)
        size = f.stream.tell()
        f.stream.seek(pos)
        if size > cfg["MAX_FILE_SIZE_BYTES"]:
            raise ValueError("One of the images exceeds 10MB.")
        cleaned.append((f, size))
    return cleaned


@requests_bp.route("/requests/<int:request_id>/transition", methods=["POST"])
@login_required
def do_transition(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)

    form = TransitionForm()
    dept = current_user.department

    possible = []
    if dept == "A":
        # Dept A: only reopen or close
        for to in ("B_IN_PROGRESS", "CLOSED"):
            if is_transition_valid_for_request(req, dept, req.status, to):
                possible.append((to, to))
    elif dept == "B":
        # Dept B: expose all B-facing destinations; actual guardrails enforced after submit
        for to in ("B_IN_PROGRESS", "WAITING_ON_A_RESPONSE", "PENDING_C_REVIEW", "C_APPROVED", "C_NEEDS_CHANGES",
                   "B_FINAL_REVIEW", "SENT_TO_A", "CLOSED"):
            if to == "WAITING_ON_A_RESPONSE":
                label = "Pending review from Department A"
            elif to == "B_IN_PROGRESS":
                label = "In progress by Department B"
            elif to == "PENDING_C_REVIEW":
                label = "Under review by Department C"
            else:
                label = to
            possible.append((to, label))
    else:
        # Dept C: only approve or request changes
        for to in ("C_APPROVED", "C_NEEDS_CHANGES"):
            if is_transition_valid_for_request(req, dept, req.status, to):
                possible.append((to, to))
    form.to_status.choices = possible

    if not form.validate_on_submit():
        flash("Transition failed validation.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    to_status = form.to_status.data

    if dept == "B":
        req.requires_c_review = bool(form.requires_c_review.data)

        if req.requires_c_review and to_status in (
            "B_IN_PROGRESS",
            "WAITING_ON_A_RESPONSE",
            "B_FINAL_REVIEW",
        ):
            to_status = "PENDING_C_REVIEW"
            flash("Requires Dept C Review is checked — routing to Department C review.", "info")

        if (not req.requires_c_review) and to_status == "PENDING_C_REVIEW":
            to_status = "B_IN_PROGRESS"
            flash("Requires Dept C Review is not checked — keeping request out of Department C review.", "info")

    if not is_transition_valid_for_request(req, dept, req.status, to_status):
        flash("That transition isn't allowed from the current status.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    from_status = req.status

    # Determine whether we should create a submission record. Create one when
    # this is a handoff (cross-department transfer) OR when the actor provided
    # a summary/details or attachments for this status update.
    handoff = handoff_for_transition(req.status, to_status)
    # If no explicit handoff rule exists but the owner department implied by the
    # target status differs from the current owner, treat this as a transfer
    # handoff (e.g., selecting a status that names a different department).
    if not handoff:
        target_owner = owner_for_status(to_status)
        if target_owner and target_owner != req.owner_department:
            handoff = (req.owner_department, target_owner)

    create_submission = False
    from_dept = None
    to_dept = None
    submission_summary_text = None
    if handoff:
        from_dept, to_dept = handoff
        create_submission = True
    else:
        # If owner would change, treat as implicit handoff
        target_owner = owner_for_status(to_status)
        if target_owner and target_owner != req.owner_department:
            from_dept = req.owner_department
            to_dept = target_owner
            create_submission = True
        else:
            # If user supplied summary/details or files, create a submission record
            has_summary = bool((form.submission_summary.data or "").strip())
            has_details = bool((form.submission_details.data or "").strip())
            has_files = bool(form.files.data and any(f and f.filename for f in form.files.data))
            if has_summary or has_details or has_files:
                from_dept = req.owner_department
                to_dept = owner_for_status(to_status) or req.owner_department
                create_submission = True

    if create_submission:
        # Require submission content only when the handoff crosses departments
        require_submission = (from_dept != to_dept)

        # Allow Dept A to close without providing a submission packet.
        if require_submission:
            if not (dept == "A" and to_status == "CLOSED"):
                if not form.submission_summary.data:
                    flash("Submission Summary is required when transferring a request to another department.", "danger")
                    return redirect(url_for("requests.request_detail", request_id=req.id))

        try:
            validated = _validate_files(form.files.data)
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("requests.request_detail", request_id=req.id))

        is_public = (to_dept == "A") or (from_dept == "A")

        sub = Submission(
            request_id=req.id,
            from_department=from_dept,
            to_department=to_dept,
            from_status=req.status,
            to_status=to_status,
            summary=(form.submission_summary.data or "").strip(),
            details=(form.submission_details.data or "").strip(),
            is_public_to_submitter=is_public,
            created_by_user_id=current_user.id,
        )
        db.session.add(sub)
        db.session.flush()
        submission_summary_text = sub.summary or None

        # attachments
        for f, size in validated:
            orig = secure_filename(f.filename)
            stored = f"{uuid.uuid4().hex}_{orig}"
            save_path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
            f.save(save_path)
            db.session.add(Attachment(
                submission_id=sub.id,
                uploaded_by_user_id=current_user.id,
                original_filename=orig,
                stored_filename=stored,
                content_type=f.mimetype,
                size_bytes=size,
            ))

        _log(req, "submission_created", note=f"Submission packet created ({from_dept}→{to_dept}).")

        # If this was an explicit handoff, set the request status/owner before notifying recipients
        if handoff:
            req.status = to_status
            req.owner_department = owner_for_status(to_status)

        # Notify receiving dept only for explicit handoffs
        if handoff:
            recipients = [u for u in _users_in_dept(to_dept) if u.id != current_user.id]
            notify_users(
                recipients,
                title=f"New handoff: {from_dept} → {to_dept} (Request #{req.id})",
                body=sub.summary,
                url=url_for("requests.request_detail", request_id=req.id),
                ntype="handoff",
                request_id=req.id,
            )

    # Update request status and owner
    req.status = to_status
    req.owner_department = owner_for_status(to_status)
    _log(req, "status_change", note=f"Status changed by Dept {dept}.", from_status=from_status, to_status=to_status)

    # Prometheus: record transition
    try:
        metrics_module.request_transitions_total.labels(from_status=from_status or "", to_status=to_status or "", dept=dept).inc()
    except Exception:
        current_app.logger.exception('Failed to record transition metric')

    # If Dept B is sending the request to Dept A, clear any assignment so
    # Dept A can decide to close or reopen/request review. Record an audit
    # entry and notify the previous assignee (if any).
    if dept == "B" and to_status == "SENT_TO_A":
        if req.assigned_to_user_id:
            previous = req.assigned_to_user
            prev_label = (previous.name or previous.email) if previous else "Unassigned"
            req.assigned_to_user = None
            _log(req, "assignment_changed", note=f"Assignment cleared as request sent to Dept A: {prev_label}")
            try:
                if previous and getattr(previous, "is_active", True):
                    notify_users([
                        previous
                    ],
                    title=f"Assignment cleared on Request #{req.id}",
                    body=(f"Your assignment was cleared because the request was sent to Department A."),
                    url=url_for("requests.request_detail", request_id=req.id),
                    ntype="assignment_cleared",
                    request_id=req.id,
                    )
                # Prometheus: assignment cleared
                try:
                    metrics_module.assignment_changes_total.labels(dept='B', action='cleared').inc()
                except Exception:
                    current_app.logger.exception('Failed to record assignment cleared metric')
            except Exception:
                current_app.logger.exception("Failed to notify previous assignee about cleared assignment")

    # Notify new owner dept (with custom messaging for Dept A actions)
    owner_recipients = [u for u in _users_in_dept(req.owner_department) if u.id != current_user.id]
    # Notify new owner dept (with custom messaging for Dept A actions)
    owner_recipients = [u for u in _users_in_dept(req.owner_department) if u.id != current_user.id]
    body_text = submission_summary_text or req.title
    if dept == "A" and to_status == "CLOSED":
        notify_users(
            owner_recipients,
            title=f"Request #{req.id} approved by Dept A",
            body=body_text,
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="status_change",
            request_id=req.id,
        )
    elif dept == "A" and to_status == "B_IN_PROGRESS":
        notify_users(
            owner_recipients,
            title=f"Request #{req.id} reopened by Dept A",
            body=body_text,
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="status_change",
            request_id=req.id,
        )
    else:
        notify_users(
            owner_recipients,
            title=f"Request #{req.id} moved to {req.status}",
            body=body_text,
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="status_change",
            request_id=req.id,
        )

    # Notify creator (if exists, and not actor)
    if req.created_by_user_id and req.created_by_user_id != current_user.id:
        creator = User.query.get(req.created_by_user_id)
        if creator and getattr(creator, "is_active", True):
            notify_users(
                [creator],
                title=f"Update on Request #{req.id}",
                body=f"Now: {req.status}",
                url=url_for("requests.request_detail", request_id=req.id),
                ntype="status_change",
                request_id=req.id,
            )

    db.session.commit()
    flash(f"Moved to {to_status}.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route("/requests/<int:request_id>/assign", methods=["POST"])
@login_required
def assign_request(request_id: int):
    req = ReqModel.query.get_or_404(request_id)
    if not can_view_request(req):
        abort(403)
    if current_user.department not in ("A", "B", "C"):
        abort(403)
    # Dept B may assign requests they own. Dept C may assign requests that
    # are awaiting C review so C users can claim/assign them locally. Dept A
    # may assign requests it owns when the request is currently owned by A.
    if not (
        (current_user.department == "B" and req.owner_department == "B") or
        (current_user.department == "C" and req.status == "PENDING_C_REVIEW" and req.requires_c_review) or
        (current_user.department == "A" and req.owner_department == "A")
    ):
        abort(403)

    form = AssignmentForm()
    form.assignee.choices = _assignment_choices(current_user.department)
    if not form.validate_on_submit():
        flash("Choose a valid assignee.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    selected_id = form.assignee.data
    new_assignee = None
    if selected_id != -1:
        new_assignee = User.query.filter_by(
            id=selected_id,
            department=current_user.department,
            is_active=True,
        ).first()
        if not new_assignee:
            flash("Invalid assignee for your department.", "danger")
            return redirect(url_for("requests.request_detail", request_id=req.id))

    previous = req.assigned_to_user
    if (previous.id if previous else None) == (new_assignee.id if new_assignee else None):
        flash("Assignment unchanged.", "info")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    req.assigned_to_user = new_assignee

    prev_label = (previous.name or previous.email) if previous else "Unassigned"
    new_label = (new_assignee.name or new_assignee.email) if new_assignee else "Unassigned"
    _log(req, "assignment_changed", note=f"Assignment changed: {prev_label} → {new_label}")

    notif_targets = []
    if new_assignee and new_assignee.id != current_user.id:
        notif_targets.append(new_assignee)
    if req.created_by_user_id and req.created_by_user_id != current_user.id:
        creator = User.query.get(req.created_by_user_id)
        if creator and getattr(creator, "is_active", True):
            notif_targets.append(creator)

    if notif_targets:
        unique = {u.id: u for u in notif_targets}.values()
        notify_users(
            unique,
            title=f"Request #{req.id} assigned to {new_label}",
            body=req.title,
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="assignment",
            request_id=req.id,
        )

    db.session.commit()
    flash("Assignment updated.", "success")
    try:
        # Prometheus: assignment changed
        metrics_module.assignment_changes_total.labels(dept=current_user.department, action='assigned' if new_assignee else 'cleared').inc()
        metrics_module.update_owner_gauge(db.session, ReqModel)
    except Exception:
        current_app.logger.exception('Failed to update metrics on assignment change')

    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route("/requests/<int:request_id>/toggle_c_review", methods=["POST"])
@login_required
def toggle_c_review(request_id: int):
    req = ReqModel.query.get_or_404(request_id)

    if current_user.department != "B":
        abort(403)
    if not can_view_request(req):
        abort(403)

    rv = _require_assigned_user(req)
    if rv:
        return rv

    if req.status not in ("NEW_FROM_A", "B_IN_PROGRESS"):
        flash("C review can only be toggled while the request is NEW_FROM_A or B_IN_PROGRESS.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    form = ToggleCReviewForm()
    if not form.validate_on_submit():
        flash("Reason is required to toggle C review.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    old_value = req.requires_c_review
    req.requires_c_review = not req.requires_c_review

    note = (
        f"Dept B toggled requires_c_review: {old_value} → {req.requires_c_review}\n"
        f"Reason:\n{form.reason.data.strip()}"
    )
    _log(req, "c_review_toggled", note=note)
    db.session.commit()

    flash(f"Requires Dept C Review set to: {req.requires_c_review}", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route("/attachments/<int:attachment_id>")
@login_required
def download_attachment(attachment_id: int):
    att = Attachment.query.get_or_404(attachment_id)
    req = att.submission.request

    if not can_view_request(req):
        abort(403)

    file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], att.stored_filename)
    if not os.path.exists(file_path):
        abort(404)

    return send_file(
        file_path,
        mimetype=att.content_type,
        as_attachment=False,
        download_name=att.original_filename,
    )
