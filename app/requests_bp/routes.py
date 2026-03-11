"""Routes and handlers for the core request workflow.

This module implements the main blueprint for creating, viewing, assigning,
and transitioning `Request` objects. It contains helper functions that
encapsulate permission checks, assignment logic, and the lightweight
in-process presence tracker used by the UI. Several endpoints also emit
Prometheus metrics (via `app/metrics.py`) when available.
"""

import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from .. import metrics as metrics_module
from .. import notifcations as notifications_module
from ..extensions import db, get_or_404
from ..models import (
    Artifact,
    Attachment,
    AuditLog,
    BucketStatus,
    Comment,
    DepartmentEditor,
    FeatureFlags,
    FormField,
    FormFieldOption,
    Notification,
    RejectRequestConfig,
)
from ..models import Request as ReqModel
from ..models import RequestApproval, SavedSearchView, StatusBucket, StatusOption
from ..models import Submission
from ..models import Submission as FormSubmission
from ..models import User
from ..notifcations import notify_users, users_in_department
from ..services.integrations import (
    build_handoff_bundle_payload,
    emit_webhook_event,
    serialize_request,
)
from ..services.process_metrics import (
    build_process_metrics_summary,
    record_process_metric_event,
)
from ..services.tenant_context import tenant_role_for_user
from ..services.ticketing import TicketingClient
from ..services.verification import VerificationService
from ..utils.user_context import get_user_departments
from . import requests_bp
from .forms import (
    ArtifactForm,
    AssignmentForm,
    CommentForm,
    DonorOnlyForm,
    RequestArtifactEditForm,
    ToggleCReviewForm,
    TransitionForm,
)
from .permissions import (
    allowed_comment_scopes_for_user,
    can_view_request,
    visible_comment_scopes_for_user,
)
from .workflow import (
    allowed_transitions_with_labels,
    handoff_for_transition,
    owner_for_status,
    transition_allowed,
)


def _metric_departments_for_user(user) -> list[str]:
    try:
        if not user or not getattr(user, "id", None):
            return []
        if getattr(user, "is_admin", False):
            return ["A", "B", "C"]
        rows = DepartmentEditor.query.filter_by(user_id=user.id).all()
        depts = sorted(
            {
                (row.department or "").strip().upper()
                for row in rows
                if getattr(row, "can_view_metrics", False)
                and (row.department or "").strip().upper() in {"A", "B", "C"}
            }
        )
        return depts
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []


def _user_is_dept_head(user, dept: str) -> bool:
    """Return True if *user* is considered the head/editor for *dept*.

    Admins are heads for everything.  Otherwise we treat a
    DepartmentEditor entry with ``can_view_metrics`` as signifying a
    department-head role (the same flag used to grant metrics access)."""
    if not user or not getattr(user, "id", None):
        return False
    if getattr(user, "is_admin", False):
        return True
    try:
        row = DepartmentEditor.query.filter_by(user_id=user.id, department=dept).first()
        return bool(row and getattr(row, "can_view_metrics", False))
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def _watched_department_links_for_user(user) -> list[dict]:
    try:
        if not user or not getattr(user, "is_authenticated", False):
            return []
        allowed = set(get_user_departments(user))
        current = (getattr(user, "department", None) or "").strip().upper()
        labels = {"A": "Dept A", "B": "Dept B", "C": "Dept C"}
        links = []
        for dept in getattr(user, "watched_departments", []) or []:
            code = (dept or "").strip().upper()
            if not code or code not in allowed or code == current:
                continue
            links.append(
                {
                    "department": code,
                    "title": labels.get(code, f"Dept {code}"),
                    "meta": "Quick access queue",
                    "href": url_for("requests.department_dashboard", dept=code),
                }
            )
        return links
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []


def _require_metrics_access(user) -> list[str]:
    allowed = _metric_departments_for_user(user)
    if not allowed:
        abort(403)
    return allowed


# Optional cache helper (Flask-Caching may not be available in some test envs).
try:
    from ..extensions import cache
except Exception:
    cache = None


def _make_cache_key(name: str) -> str:
    return f"requests:{name}"


def cached_view(timeout: int = 60, prefix: str = None):
    def _decorator(f):
        return f

    return _decorator


_presence: Dict[int, Dict[int, Dict[str, object]]] = {}


def _users_in_dept(dept: str):
    return users_in_department(dept)


MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
APPROVAL_STATUSES = {"PENDING_C_REVIEW", "EXEC_APPROVAL"}


def _approval_status_codes() -> tuple:
    codes = set(APPROVAL_STATUSES)
    try:
        codes.update(
            code
            for code, raw_json in db.session.query(
                StatusOption.code, StatusOption.approval_stages_json
            ).all()
            if raw_json
        )
    except Exception:
        pass
    return tuple(sorted(codes))


def _sla_state_for_request(
    req: ReqModel, now: Optional[datetime] = None
) -> Optional[str]:
    now = now or datetime.utcnow()
    due_at = getattr(req, "due_at", None)
    if not due_at or getattr(req, "status", None) == "CLOSED":
        return None
    if due_at < now:
        return "breached"

    hours_left = (due_at - now).total_seconds() / 3600.0
    priority = (getattr(req, "priority", "medium") or "medium").strip().lower()
    threshold_hours = {
        "high": 24,
        "medium": 48,
        "low": 72,
    }.get(priority, 48)
    if hours_left <= threshold_hours:
        return "at_risk"
    return "on_track"


def _mentioned_recipients_for_comment(req: ReqModel, body: str) -> list[User]:
    emails = {
        match.group(1).strip().lower() for match in MENTION_RE.finditer(body or "")
    }
    if not emails:
        return []

    allowed_user_ids = {
        getattr(u, "id", None)
        for u in _users_in_dept(getattr(req, "owner_department", None))
    }
    if getattr(req, "created_by_user_id", None):
        allowed_user_ids.add(req.created_by_user_id)
    if getattr(req, "assigned_to_user_id", None):
        allowed_user_ids.add(req.assigned_to_user_id)

    mentioned = []
    for email in emails:
        user = User.query.filter(func.lower(User.email) == email).first()
        if not user or not getattr(user, "is_active", True):
            continue
        if user.id == getattr(current_user, "id", None):
            continue
        if getattr(user, "is_admin", False) or user.id in allowed_user_ids:
            mentioned.append(user)

    unique = {}
    for user in mentioned:
        unique[user.id] = user
    return list(unique.values())


def _saved_views_for_current_user(limit: int = 8) -> list[SavedSearchView]:
    if not getattr(current_user, "is_authenticated", False):
        return []
    return (
        SavedSearchView.query.filter_by(user_id=current_user.id)
        .order_by(SavedSearchView.is_default.desc(), SavedSearchView.updated_at.desc())
        .limit(limit)
        .all()
    )


def _normalized_saved_view_params(source) -> dict[str, str]:
    raw = {
        "q": (source.get("q") or "").strip(),
        "status": (source.get("status") or "").strip().upper(),
        "priority": (source.get("priority") or source.get("priority_filter") or "")
        .strip()
        .lower(),
        "sla": (source.get("sla") or "").strip().lower(),
        "approval_only": (
            "1"
            if (source.get("approval_only") or "").strip().lower()
            in {"1", "true", "yes", "on"}
            else ""
        ),
    }
    return {k: v for k, v in raw.items() if v}


def _request_list_query(q):
    # Minimal passthrough used by dashboard; real implementation may add
    # filters for hidden/archived requests.
    return q


def scope_requests_for_department(q, dept: str):
    # Scope queries to requests relevant to a department. Keep conservative
    # default: owner_department == dept.
    try:
        return q.filter(ReqModel.owner_department == dept)
    except Exception:
        return q


def _exclude_old_closed(q):
    return q


def _assignment_choices(dept: str):
    try:
        users = (
            User.query.filter_by(department=dept, is_active=True)
            .order_by(User.name.asc(), User.email.asc())
            .all()
        )
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            current_app.logger.exception(
                "Failed to load assignment choices for department %s", dept
            )
        except Exception:
            pass
        return [(-1, "Unassigned")]
    return [(-1, "Unassigned")] + [
        (u.id, u.name or u.email or f"User #{u.id}") for u in users
    ]


def _require_assigned_user(req: ReqModel):
    assigned_to_user_id = getattr(req, "assigned_to_user_id", None)
    if assigned_to_user_id == getattr(current_user, "id", None):
        return None

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        if assigned_to_user_id is None:
            return jsonify({"ok": False, "message": "Assign the request first."}), 409
        return (
            jsonify(
                {"ok": False, "message": "This request is assigned to another user."}
            ),
            403,
        )

    if assigned_to_user_id is None:
        flash("Assign the request before making changes.", "warning")
    else:
        flash("This request is assigned to another user.", "warning")
    return redirect(url_for("requests.request_detail", request_id=req.id))


def _success_response(message: str, req: ReqModel):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "message": message, "request_id": req.id})
    flash(message, "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))


def can_edit_artifact(req: ReqModel, artifact: Artifact, dept: str) -> bool:
    if dept == "A":
        return bool(
            req.owner_department == "A" or getattr(artifact, "edit_requested", False)
        )
    if dept == "C":
        return bool(
            getattr(req, "requires_c_review", False) or req.status == "PENDING_C_REVIEW"
        )
    return dept == "B"


def can_add_artifact(req: ReqModel, dept: str, artifact_type: Optional[str]) -> bool:
    if dept == "A":
        return req.owner_department == "A"
    if dept == "C":
        return bool(
            getattr(req, "requires_c_review", False) or req.status == "PENDING_C_REVIEW"
        )
    return dept == "B"


def _log(req, action_type, note=None, from_status=None, to_status=None):
    try:
        a = AuditLog(
            request_id=getattr(req, "id", None),
            actor_type="user",
            actor_user_id=getattr(current_user, "id", None),
            actor_label=getattr(current_user, "email", None),
            action_type=action_type,
            from_status=from_status,
            to_status=to_status,
            note=note,
        )
        db.session.add(a)
    except Exception:
        try:
            current_app.logger.exception("Failed to write audit log")
        except Exception:
            pass


def _annotate_last_owner_statuses(buckets: Dict[str, List[ReqModel]]) -> None:
    """Bulk-populate `last_owner_status` to avoid per-request audit queries."""
    request_rows = []
    for reqs in buckets.values():
        request_rows.extend(reqs)

    if not request_rows:
        return

    request_ids = []
    owner_dept_by_id = {}
    seen = set()
    for req in request_rows:
        if req.id not in seen:
            seen.add(req.id)
            request_ids.append(req.id)
            owner_dept_by_id[req.id] = req.owner_department

    last_status_by_request = {}
    try:
        rows = (
            db.session.query(AuditLog.request_id, AuditLog.to_status, User.department)
            .join(User, AuditLog.actor_user)
            .filter(
                AuditLog.request_id.in_(request_ids),
                AuditLog.action_type == "status_change",
            )
            .order_by(AuditLog.request_id.asc(), AuditLog.created_at.desc())
            .all()
        )
        for request_id, to_status, actor_department in rows:
            if request_id in last_status_by_request:
                continue
            if owner_dept_by_id.get(request_id) == actor_department and to_status:
                last_status_by_request[request_id] = to_status
    except Exception:
        last_status_by_request = {}

    for req in request_rows:
        req.last_owner_status = last_status_by_request.get(req.id, req.status)


def _closed_within_hours(req: ReqModel, hours: int = 48) -> bool:
    """Return True if the request was moved to CLOSED within the last `hours` hours."""
    entry = (
        AuditLog.query.filter_by(request_id=req.id, action_type="status_change")
        .filter(AuditLog.to_status == "CLOSED")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    if not entry:
        return False
    return (datetime.utcnow() - entry.created_at) <= timedelta(hours=hours)


def _recent_status_change_entries(req_id: int, hours: int = 24, limit: int = 12):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    try:
        return (
            AuditLog.query.filter_by(request_id=req_id, action_type="status_change")
            .filter(AuditLog.created_at >= cutoff)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .all()
        )
    except Exception:
        return []


def _detect_recent_transition_loop(
    req_id: int, from_status: str, to_status: str, *, hours: int = 24
):
    """Return a warning string when a request is bouncing between two statuses.

    The guard blocks a third move in the same reciprocal pair within the
    recent window, which prevents accidental ping-pong between teams without
    blocking a single legitimate correction or reopen.
    """
    if not req_id or not from_status or not to_status or from_status == to_status:
        return None

    recent = _recent_status_change_entries(req_id, hours=hours)
    if len(recent) < 2:
        return None

    pair = {from_status, to_status}
    pair_hits = [
        entry
        for entry in recent
        if {entry.from_status, entry.to_status} == pair
        and entry.from_status
        and entry.to_status
    ]
    if len(pair_hits) < 2:
        return None

    latest = recent[0]
    if latest.from_status == to_status and latest.to_status == from_status:
        return (
            f"This request has already bounced between {from_status} and {to_status} multiple times in the last {hours} hours. "
            "Update the summary/details first or choose a different next step to avoid a process loop."
        )
    return None


def _build_recent_status_path(audit_entries, current_status: str):
    path = []
    for entry in audit_entries or []:
        if entry.to_status and (not path or path[-1] != entry.to_status):
            path.append(entry.to_status)
    if not path or path[-1] != current_status:
        path.append(current_status)
    return path[-6:]


ROLE_PRIORITY = {
    "viewer": 0,
    "member": 1,
    "analyst": 2,
    "tenant_admin": 3,
    "platform_admin": 4,
}

APPROVAL_TRANSITIONS_REQUIRING_COMPLETION = {
    ("PENDING_C_REVIEW", "C_APPROVED"),
    ("EXEC_APPROVAL", "SENT_TO_A"),
}


def _role_satisfies_requirement(
    actual_role: Optional[str], required_role: Optional[str]
) -> bool:
    if not required_role:
        return True
    return ROLE_PRIORITY.get(actual_role or "", -1) >= ROLE_PRIORITY.get(
        required_role, ROLE_PRIORITY.get("platform_admin", 4) + 1
    )


def _approval_stage_definitions_for_status(status_code: Optional[str]) -> list:
    if not status_code:
        return []
    try:
        opt = StatusOption.query.filter_by(code=status_code).first()
        return list(getattr(opt, "approval_stages", []) or []) if opt else []
    except Exception:
        return []


def _current_approval_rows(request_id: int, status_code: Optional[str]):
    if not request_id or not status_code:
        return []
    try:
        rows = (
            RequestApproval.query.filter_by(
                request_id=request_id, status_code=status_code
            )
            .order_by(
                RequestApproval.cycle_index.desc(), RequestApproval.stage_order.asc()
            )
            .all()
        )
    except Exception:
        return []
    if not rows:
        return []
    latest_cycle = rows[0].cycle_index
    return [row for row in rows if row.cycle_index == latest_cycle]


def _approval_history_rows(request_id: int, status_code: Optional[str]):
    if not request_id or not status_code:
        return []
    current_rows = _current_approval_rows(request_id, status_code)
    current_cycle = current_rows[0].cycle_index if current_rows else None
    try:
        query = RequestApproval.query.filter_by(
            request_id=request_id, status_code=status_code
        )
        if current_cycle is not None:
            query = query.filter(RequestApproval.cycle_index < current_cycle)
        return query.order_by(
            RequestApproval.cycle_index.desc(),
            RequestApproval.stage_order.asc(),
            RequestApproval.created_at.desc(),
        ).all()
    except Exception:
        return []


def _user_can_signoff_approval(
    approval: RequestApproval, user, cycle_rows=None
) -> bool:
    if not approval or not user or approval.state != "pending":
        return False
    if approval.required_department:
        user_department = (getattr(user, "department", "") or "").upper()
        if user_department != (approval.required_department or "").upper():
            return False
    if not _role_satisfies_requirement(
        tenant_role_for_user(user), approval.required_role
    ):
        return False
    rows = (
        cycle_rows
        if cycle_rows is not None
        else _current_approval_rows(approval.request_id, approval.status_code)
    )
    for row in rows or []:
        if row.cycle_index != approval.cycle_index:
            continue
        if row.stage_order >= approval.stage_order:
            break
        if row.state != "approved":
            return False
    return True


def _approval_cycle_state(
    request_id: int, status_code: Optional[str], user=None
) -> dict:
    current_rows = _current_approval_rows(request_id, status_code)
    ready = bool(current_rows) and all(row.state == "approved" for row in current_rows)
    blocked = any(row.state == "changes_requested" for row in current_rows)
    actionable = (
        [
            row
            for row in current_rows
            if _user_can_signoff_approval(row, user, current_rows)
        ]
        if user
        else []
    )
    return {
        "current_rows": current_rows,
        "history_rows": _approval_history_rows(request_id, status_code),
        "ready": ready,
        "blocked": blocked,
        "actionable_rows": actionable,
        "actionable_ids": [row.id for row in actionable],
        "has_configured_stages": bool(
            _approval_stage_definitions_for_status(status_code)
        ),
    }


def _create_approval_cycle_for_status(req: ReqModel, status_code: Optional[str]):
    stages = _approval_stage_definitions_for_status(status_code)
    if not stages:
        return []
    try:
        latest_cycle = (
            db.session.query(func.max(RequestApproval.cycle_index))
            .filter_by(request_id=req.id, status_code=status_code)
            .scalar()
            or 0
        )
    except Exception:
        latest_cycle = 0
    cycle_index = latest_cycle + 1
    created = []
    for idx, stage in enumerate(stages, start=1):
        created.append(
            RequestApproval(
                tenant_id=getattr(req, "tenant_id", None),
                request_id=req.id,
                status_code=status_code,
                cycle_index=cycle_index,
                stage_order=idx,
                stage_name=stage.get("name") or f"Stage {idx}",
                required_role=stage.get("role") or None,
                required_department=stage.get("department") or None,
                state="pending",
            )
        )
    db.session.add_all(created)
    _log(
        req,
        "approval_decision",
        note=f"Approval cycle {cycle_index} started for {status_code} with {len(created)} stage(s).",
        from_status=status_code,
        to_status=status_code,
    )
    return created


def _approval_transition_requires_completion(from_status: str, to_status: str) -> bool:
    return (from_status, to_status) in APPROVAL_TRANSITIONS_REQUIRING_COMPLETION


def _approval_dashboard_cards(user, scoped_requests) -> list:
    cards = []
    requests_list = list(scoped_requests or [])
    if not user or not requests_list:
        return cards

    needs_my_signoff = 0
    awaiting_others = 0
    ready_for_next_step = 0

    for req in requests_list:
        snapshot = _approval_cycle_state(req.id, req.status, user=user)
        if not snapshot["current_rows"]:
            continue
        if snapshot["ready"]:
            ready_for_next_step += 1
        elif snapshot["actionable_rows"]:
            needs_my_signoff += 1
        else:
            awaiting_others += 1

    cards.append(
        {
            "title": "Needs my signoff",
            "count": needs_my_signoff,
            "description": "Requests where you can approve the next stage right now.",
            "href": url_for("requests.search_requests", approval_only="1"),
        }
    )
    cards.append(
        {
            "title": "Awaiting others",
            "count": awaiting_others,
            "description": "Approval work still waiting on another role or department.",
            "href": url_for("requests.search_requests", approval_only="1"),
        }
    )
    cards.append(
        {
            "title": "Ready for next step",
            "count": ready_for_next_step,
            "description": "All configured signoffs are complete and the request can move forward.",
            "href": url_for("requests.search_requests", approval_only="1"),
        }
    )
    return cards


# Notification helpers are provided by app/notifcations.py (imported above)


def is_transition_valid_for_request(
    req: ReqModel, dept: str, from_status: str, to_status: str
) -> bool:
    from sqlalchemy.orm.exc import DetachedInstanceError

    if not transition_allowed(dept, from_status, to_status):
        return False

    # Attempt to read required fields from the provided `req` instance.
    # If the instance is detached/expired, fall back to a lightweight
    # DB query that fetches only the required columns to avoid
    # DetachedInstanceError during attribute refresh.
    try:
        requires_c = bool(getattr(req, "requires_c_review", False))
        pricebook = getattr(req, "pricebook_status", None)
    except DetachedInstanceError:
        try:
            row = (
                db.session.query(ReqModel.requires_c_review, ReqModel.pricebook_status)
                .filter(ReqModel.id == getattr(req, "id", None))
                .one()
            )
            requires_c = bool(row[0])
            pricebook = row[1]
        except Exception:
            # If even the fallback query fails, be conservative and block the transition
            return False

    # If C review is required: block bypass to final review
    if (
        requires_c
        and to_status == "B_FINAL_REVIEW"
        and from_status
        in (
            "NEW_FROM_A",
            "B_IN_PROGRESS",
        )
    ):
        return False

    # If C review is NOT required: block sending to C (for all depts)
    if (not requires_c) and to_status == "PENDING_C_REVIEW":
        return False

    # Allow UNDER_REVIEW only for non-sales-list items or when coming back from C approval
    if to_status == "UNDER_REVIEW":
        # If this transition is after C approval (C -> B), allow regardless of sales list
        if from_status == "C_APPROVED":
            return True
        # Otherwise, only allow if the request is NOT on the sales list
        if pricebook == "in_pricebook":
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
@cached_view(timeout=30, prefix="dashboard")
def dashboard():
    # Default to the current user's department. Admins may pass ?as_dept=A|B|C to view other departments.
    dept = current_user.department
    if getattr(current_user, "is_admin", False):
        as_dept = (request.args.get("as_dept") or "").upper()
        if as_dept in ("A", "B", "C"):
            dept = as_dept

    artifact_form = ArtifactForm()
    saved_views = _saved_views_for_current_user()
    watched_department_links = _watched_department_links_for_user(current_user)

    # expose an assignment picker for dept heads in the bucket UI
    can_bulk_assign = _user_is_dept_head(current_user, dept)
    assignment_form = AssignmentForm()
    assignment_form.assignee.choices = _assignment_choices(dept)

    # common bucket lookup for all departments (global or scoped to current dept)
    status_filter = request.args.get("status")
    bucket_id = request.args.get("bucket_id")
    selected_bucket_mode = False

    bucket_list = (
        StatusBucket.query.filter(StatusBucket.active == True)
        .filter(
            (StatusBucket.department_name == None)
            | (StatusBucket.department_name == "")
            | (StatusBucket.department_name == dept)
        )
        .order_by(StatusBucket.order.asc())
        .all()
    )
    # seed dept-B defaults if completely empty (analogous to startup code)
    if dept == "B" and not bucket_list:
        try:
            nb = StatusBucket(name="New", department_name="B", order=0, active=True)
            db.session.add(nb)
            db.session.flush()
            db.session.add(
                BucketStatus(bucket_id=nb.id, status_code="NEW_FROM_A", order=0)
            )
            ip = StatusBucket(
                name="In Progress", department_name="B", order=1, active=True
            )
            db.session.add(ip)
            db.session.flush()
            db.session.add(
                BucketStatus(bucket_id=ip.id, status_code="B_IN_PROGRESS", order=0)
            )
            db.session.add(
                BucketStatus(bucket_id=ip.id, status_code="PENDING_C_REVIEW", order=1)
            )
            db.session.add(
                BucketStatus(bucket_id=ip.id, status_code="B_FINAL_REVIEW", order=2)
            )
            ni = StatusBucket(
                name="Needs Info", department_name="B", order=2, active=True
            )
            db.session.add(ni)
            db.session.flush()
            db.session.add(
                BucketStatus(bucket_id=ni.id, status_code="NEEDS_INFO", order=0)
            )
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        bucket_list = (
            StatusBucket.query.filter(StatusBucket.active == True)
            .filter(
                (StatusBucket.department_name == None)
                | (StatusBucket.department_name == "")
                | (StatusBucket.department_name == dept)
            )
            .order_by(StatusBucket.order.asc())
            .all()
        )

    bucket_status_map = {bucket.id: [] for bucket in bucket_list}
    if bucket_status_map:
        bucket_status_rows = (
            BucketStatus.query.filter(
                BucketStatus.bucket_id.in_(bucket_status_map.keys())
            )
            .order_by(BucketStatus.bucket_id.asc(), BucketStatus.order.asc())
            .all()
        )
        for bucket_status in bucket_status_rows:
            bucket_status_map.setdefault(bucket_status.bucket_id, []).append(
                bucket_status.status_code
            )

    # helper to compute counts for current bucket_list using provided base query
    # 'Unassigned' buckets should count only requests with no assignee; they are
    # otherwise treated as a catch-all so we don't inject status filters.
    def _compute_status_counts(base_q):
        counts = {}
        for b in bucket_list:
            # start with base query for department-scoped items
            q = base_q
            namekey = (b.name or "").strip().lower()
            if namekey == "unassigned":
                q = q.filter(ReqModel.assigned_to_user_id.is_(None))
            # apply status restrictions if bucket has statuses defined
            scs = bucket_status_map.get(b.id, [])
            if scs:
                q = q.filter(ReqModel.status.in_(scs))
            counts[b.id] = q.count()
        return counts

    # Allow filtering by bucket for any department; we handle mode-specific semantics below
    if bucket_id:
        selected_bucket_mode = True
        b = db.session.get(StatusBucket, int(bucket_id))
        if b:
            status_codes = bucket_status_map.get(b.id, [])
            bucket_namekey = (b.name or "").strip().lower()
        else:
            status_codes = None
            bucket_namekey = None

    if dept == "A":
        # Dept A should see all open requests owned by Department A
        base_a = _exclude_old_closed(
            _request_list_query(ReqModel.query).filter_by(owner_department="A")
        )

        if bucket_id:
            if status_codes is None:
                items = []
            else:
                q = base_a
                if status_codes:
                    q = q.filter(ReqModel.status.in_(status_codes))
                # apply unassigned filter if asked
                if bucket_namekey == "unassigned":
                    q = q.filter(ReqModel.assigned_to_user_id.is_(None))
                items = q.order_by(ReqModel.updated_at.desc()).all()
            status_counts = _compute_status_counts(base_a)
            return render_template(
                "dashboard.html",
                mode="A",
                requests=items,
                bucket_list=bucket_list,
                status_counts=status_counts,
                now=datetime.utcnow(),
                artifact_form=artifact_form,
                saved_views=saved_views,
                watched_department_links=watched_department_links,
                approval_cards=[],
            )

        # no bucket filter; show all
        my_reqs = base_a.order_by(ReqModel.updated_at.desc()).all()
        status_counts = _compute_status_counts(base_a)
        return render_template(
            "dashboard.html",
            mode="A",
            requests=my_reqs,
            bucket_list=bucket_list,
            status_counts=status_counts,
            now=datetime.utcnow(),
            artifact_form=artifact_form,
            saved_views=saved_views,
            watched_department_links=watched_department_links,
            approval_cards=[],
        )

    if dept == "B":
        # existing B-specific code follows unchanged
        # Allow filtering by a single status via query param `status` or by bucket via `bucket_id`
        selected_bucket_mode = selected_bucket_mode
        # Build base query scoped to Dept B (owned by B or explicitly sent to B)
        base_b = _request_list_query(scope_requests_for_department(ReqModel.query, "B"))
        # cutoff for 'closed this week' — start of current week (Monday 00:00 UTC)
        now = datetime.utcnow()
        closed_cutoff = datetime(now.year, now.month, now.day) - timedelta(
            days=now.weekday()
        )
        # bucket_list already prepared above

        # first handle bucket selection explicitly (works for any department)
        if bucket_id:
            selected_bucket_mode = True
            b = db.session.get(StatusBucket, int(bucket_id))
            if not b:
                items = []
            else:
                status_codes = bucket_status_map.get(b.id, [])
                q = base_b
                if status_codes:
                    q = q.filter(ReqModel.status.in_(status_codes))
                if bucket_namekey == "unassigned":
                    q = q.filter(ReqModel.assigned_to_user_id.is_(None))
                items = q.order_by(ReqModel.updated_at.desc()).all()
            label = b.name if b else "Bucket"
            buckets = {label: items}
            status_counts = {}
            _annotate_last_owner_statuses(buckets)

            return render_template(
                "dashboard.html",
                mode="B",
                buckets=buckets,
                status_counts=status_counts,
                now=datetime.utcnow(),
                artifact_form=artifact_form,
                saved_views=saved_views,
                watched_department_links=watched_department_links,
                approval_cards=_approval_dashboard_cards(current_user, items),
            )

        # legacy status filter semantics if no bucket selected
        if status_filter:
            sf = status_filter
            if sf == "in_progress":
                items = (
                    base_b.filter(
                        ReqModel.status == "B_IN_PROGRESS",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all()
                )
            elif sf == "method_created":
                items = (
                    base_b.join(Artifact)
                    .filter(
                        Artifact.artifact_type == "instructions",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .distinct()
                    .all()
                )
            elif sf == "part_number_created":
                items = (
                    base_b.join(Artifact)
                    .filter(
                        Artifact.artifact_type == "part_number",
                        (Artifact.target_part_number.isnot(None))
                        | (Artifact.donor_part_number.isnot(None)),
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .distinct()
                    .all()
                )
            elif sf == "under_review_by_department_c":
                items = (
                    base_b.filter(
                        ReqModel.status == "PENDING_C_REVIEW",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all()
                )
            elif sf == "waiting_on_department_a":
                items = (
                    base_b.filter(
                        ReqModel.status == "WAITING_ON_A_RESPONSE",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all()
                )
            elif sf == "under_final_review":
                items = (
                    base_b.filter(
                        ReqModel.status == "B_FINAL_REVIEW",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all()
                )
            elif sf == "exec_approval":
                items = (
                    base_b.filter(
                        ReqModel.status == "EXEC_APPROVAL",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all()
                )
            elif sf == "request_denied":
                items = (
                    base_b.filter(
                        ReqModel.status == "CLOSED",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all()
                )
            else:
                items = (
                    base_b.filter(
                        ReqModel.status == status_filter,
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all()
                )

            label = STATUS_LABELS.get(status_filter, status_filter)
            buckets = {label: items}
            status_counts = {}
        else:
            # No specific filter: build buckets from configured StatusBucket entries
            buckets = {}
            status_counts = {}
            for b in bucket_list:
                q = base_b
                namekey = (b.name or "").strip().lower()
                if namekey == "unassigned":
                    q = q.filter(ReqModel.assigned_to_user_id.is_(None))
                status_codes = bucket_status_map.get(b.id, [])
                if status_codes:
                    q = q.filter(ReqModel.status.in_(status_codes))
                items = q.order_by(ReqModel.updated_at.desc()).all()
                buckets[b.name] = items
                status_counts[b.id] = q.count()

        # Semantic status filters for Dept B dashboard
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
        if not selected_bucket_mode:
            if status_filter:
                sf = status_filter
                if sf == "in_progress":
                    items = (
                        base_b.filter(
                            ReqModel.status == "B_IN_PROGRESS",
                        )
                        .order_by(ReqModel.updated_at.desc())
                        .all()
                    )
                elif sf == "method_created":
                    # Requests with an 'instructions' artifact
                    items = (
                        base_b.join(Artifact)
                        .filter(
                            Artifact.artifact_type == "instructions",
                        )
                        .order_by(ReqModel.updated_at.desc())
                        .distinct()
                        .all()
                    )
                elif sf == "part_number_created":
                    # Requests with a part_number artifact that has any part number filled
                    items = (
                        base_b.join(Artifact)
                        .filter(
                            Artifact.artifact_type == "part_number",
                            (Artifact.target_part_number.isnot(None))
                            | (Artifact.donor_part_number.isnot(None)),
                        )
                        .order_by(ReqModel.updated_at.desc())
                        .distinct()
                        .all()
                    )
                elif sf == "under_review_by_department_c":
                    items = (
                        base_b.filter(
                            ReqModel.status == "PENDING_C_REVIEW",
                        )
                        .order_by(ReqModel.updated_at.desc())
                        .all()
                    )
                elif sf == "waiting_on_department_a":
                    items = (
                        base_b.filter(
                            ReqModel.status == "WAITING_ON_A_RESPONSE",
                        )
                        .order_by(ReqModel.updated_at.desc())
                        .all()
                    )
                elif sf == "under_final_review":
                    items = (
                        base_b.filter(
                            ReqModel.status == "B_FINAL_REVIEW",
                        )
                        .order_by(ReqModel.updated_at.desc())
                        .all()
                    )
                elif sf == "exec_approval":
                    items = (
                        base_b.filter(
                            ReqModel.status == "EXEC_APPROVAL",
                        )
                        .order_by(ReqModel.updated_at.desc())
                        .all()
                    )
                elif sf == "request_denied":
                    items = (
                        base_b.filter(
                            ReqModel.status == "CLOSED",
                        )
                        .order_by(ReqModel.updated_at.desc())
                        .all()
                    )
                else:
                    # fallback: treat as raw status code
                    items = (
                        base_b.filter(
                            ReqModel.status == status_filter,
                        )
                        .order_by(ReqModel.updated_at.desc())
                        .all()
                    )

                label = STATUS_LABELS.get(status_filter, status_filter)
                buckets = {label: items}
            else:
                buckets = {
                    "New from A": base_b.filter(
                        ReqModel.status == "NEW_FROM_A",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all(),
                    "In progress by Department B": base_b.filter(
                        ReqModel.status == "B_IN_PROGRESS",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all(),
                    "Pending review from Department A": base_b.filter(
                        ReqModel.status == "WAITING_ON_A_RESPONSE",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all(),
                    "Needs changes": base_b.filter(
                        ReqModel.status == "C_NEEDS_CHANGES",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all(),
                    "Exec approval required": base_b.filter(
                        ReqModel.status == "EXEC_APPROVAL",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all(),
                    "Approved by C": base_b.filter(
                        ReqModel.status == "C_APPROVED",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all(),
                    "Final review": base_b.filter(
                        ReqModel.status == "B_FINAL_REVIEW",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all(),
                    "Sent to A": base_b.filter(
                        ReqModel.status == "SENT_TO_A",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all(),
                    "Under review by Department C": base_b.filter(
                        ReqModel.status == "PENDING_C_REVIEW",
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all(),
                    "Closed this week": base_b.filter(
                        ReqModel.status == "CLOSED",
                        ReqModel.updated_at >= closed_cutoff,
                    )
                    .order_by(ReqModel.updated_at.desc())
                    .all(),
                    "All (B)": base_b.order_by(ReqModel.updated_at.desc()).all(),
                }
        else:
            buckets = {
                "New from A": base_b.filter(
                    ReqModel.status == "NEW_FROM_A",
                )
                .order_by(ReqModel.updated_at.desc())
                .all(),
                "In progress by Department B": base_b.filter(
                    ReqModel.status == "B_IN_PROGRESS",
                )
                .order_by(ReqModel.updated_at.desc())
                .all(),
                "Pending review from Department A": base_b.filter(
                    ReqModel.status == "WAITING_ON_A_RESPONSE",
                )
                .order_by(ReqModel.updated_at.desc())
                .all(),
                "Needs changes": base_b.filter(
                    ReqModel.status == "C_NEEDS_CHANGES",
                )
                .order_by(ReqModel.updated_at.desc())
                .all(),
                "Exec approval required": base_b.filter(
                    ReqModel.status == "EXEC_APPROVAL",
                )
                .order_by(ReqModel.updated_at.desc())
                .all(),
                "Approved by C": base_b.filter(
                    ReqModel.status == "C_APPROVED",
                )
                .order_by(ReqModel.updated_at.desc())
                .all(),
                "Final review": base_b.filter(
                    ReqModel.status == "B_FINAL_REVIEW",
                )
                .order_by(ReqModel.updated_at.desc())
                .all(),
                "Sent to A": base_b.filter(
                    ReqModel.status == "SENT_TO_A",
                )
                .order_by(ReqModel.updated_at.desc())
                .all(),
                "Under review by Department C": base_b.filter(
                    ReqModel.status == "PENDING_C_REVIEW",
                )
                .order_by(ReqModel.updated_at.desc())
                .all(),
                "Closed this week": base_b.filter(
                    ReqModel.status == "CLOSED",
                    ReqModel.updated_at >= closed_cutoff,
                )
                .order_by(ReqModel.updated_at.desc())
                .all(),
                "All (B)": base_b.order_by(ReqModel.updated_at.desc()).all(),
            }
        _annotate_last_owner_statuses(buckets)

        return render_template(
            "dashboard.html",
            mode="B",
            buckets=buckets,
            status_counts=status_counts,
            now=datetime.utcnow(),
            artifact_form=artifact_form,
            assignment_form=assignment_form,
            can_bulk_assign=can_bulk_assign,
            saved_views=saved_views,
            watched_department_links=watched_department_links,
            approval_cards=_approval_dashboard_cards(
                current_user,
                [req for bucket_items in buckets.values() for req in bucket_items],
            ),
        )

    if dept == "C":
        # Dept C normally sees only items awaiting C review
        base_c = _request_list_query(ReqModel.query)

        if bucket_id:
            if status_codes is None:
                items = []
            else:
                q = base_c
                if status_codes:
                    q = q.filter(ReqModel.status.in_(status_codes))
                if bucket_namekey == "unassigned":
                    q = q.filter(ReqModel.assigned_to_user_id.is_(None))
                items = q.order_by(ReqModel.updated_at.desc()).all()
            status_counts = _compute_status_counts(base_c)
            return render_template(
                "dashboard.html",
                mode="C",
                requests=items,
                bucket_list=bucket_list,
                status_counts=status_counts,
                now=datetime.utcnow(),
                artifact_form=artifact_form,
                assignment_form=assignment_form,
                can_bulk_assign=can_bulk_assign,
                saved_views=saved_views,
                watched_department_links=watched_department_links,
                approval_cards=_approval_dashboard_cards(current_user, items),
            )

        pending = (
            base_c.filter_by(status="PENDING_C_REVIEW")
            .order_by(ReqModel.updated_at.desc())
            .all()
        )
        status_counts = _compute_status_counts(base_c)
        return render_template(
            "dashboard.html",
            mode="C",
            requests=pending,
            bucket_list=bucket_list,
            status_counts=status_counts,
            now=datetime.utcnow(),
            artifact_form=artifact_form,
            assignment_form=assignment_form,
            can_bulk_assign=can_bulk_assign,
            saved_views=saved_views,
            watched_department_links=watched_department_links,
            approval_cards=_approval_dashboard_cards(current_user, pending),
        )

    abort(403)


@requests_bp.route("/departments/<dept>/dashboard")
@login_required
def department_dashboard(dept: str):
    """Convenience route to view a specific department's dashboard.

    Admins may view any department. Non-admins may view their primary
    department or any explicitly assigned departments.
    """
    code = (dept or "").strip().upper()
    if code not in ("A", "B", "C"):
        abort(404)

    allowed = False
    if getattr(current_user, "is_admin", False):
        allowed = True
    if getattr(current_user, "department", None) == code:
        allowed = True
    if not allowed:
        try:
            from ..models import UserDepartment

            ud = UserDepartment.query.filter_by(
                user_id=current_user.id, department=code
            ).first()
            if ud:
                allowed = True
        except Exception:
            pass

    if not allowed:
        abort(403)

    return redirect(url_for("requests.dashboard", as_dept=code))


@requests_bp.route("/dashboard/assign_bucket", methods=["POST"])
@login_required
def assign_bucket():
    """Bulk-assign all items currently in a bucket to a user.

    This endpoint is primarily surfaced to department heads via the
    dashboard UI.  It respects the same one-assignment-per-user rule
    enforced by :func:`assign_request`.
    """
    # determine department in the same way the dashboard does
    dept = current_user.department
    if getattr(current_user, "is_admin", False):
        as_dept = (request.form.get("as_dept") or "").upper()
        if as_dept in ("A", "B", "C"):
            dept = as_dept

    if not _user_is_dept_head(current_user, dept):
        abort(403)

    form = AssignmentForm()
    form.assignee.choices = _assignment_choices(dept)
    bucket_id = request.form.get("bucket_id")
    if not form.validate_on_submit() or not bucket_id:
        flash("Choose a valid assignee and bucket.", "danger")
        return redirect(url_for("requests.dashboard"))

    selected_id = form.assignee.data
    new_assignee = None
    if selected_id != -1:
        new_assignee = User.query.filter_by(
            id=selected_id, department=dept, is_active=True
        ).first()
        if not new_assignee:
            flash("Invalid assignee for your department.", "danger")
            return redirect(url_for("requests.dashboard"))

    # resolve bucket statuses to know which requests to touch
    try:
        b = db.session.get(StatusBucket, int(bucket_id))
    except Exception:
        b = None
    status_codes = []
    if b:
        status_codes = [
            s.status_code for s in b.statuses.order_by(BucketStatus.order.asc()).all()
        ]

    # fetch requests that live in this bucket and department
    query = ReqModel.query.filter(ReqModel.owner_department == dept)
    if status_codes:
        query = query.filter(ReqModel.status.in_(status_codes))
    requests = query.all()

    # enforce assignment rules similar to assign_request
    if new_assignee:
        # check for any other active assignment outside this set
        existing = (
            ReqModel.query.filter(
                ReqModel.assigned_to_user_id == new_assignee.id,
                ReqModel.status != "CLOSED",
                ReqModel.is_denied == False,
                ~ReqModel.id.in_([r.id for r in requests]),
            )
            .order_by(ReqModel.created_at.asc())
            .first()
        )
        if existing:
            flash(
                f"{new_assignee.name or new_assignee.email} is already assigned to Request #{existing.id}. Clear that assignment first.",
                "warning",
            )
            return redirect(url_for("requests.dashboard"))

    # perform assignments
    any_changed = False
    for req in requests:
        previous = (
            db.session.get(User, req.assigned_to_user_id)
            if req.assigned_to_user_id
            else None
        )
        if (previous.id if previous else None) == (
            new_assignee.id if new_assignee else None
        ):
            continue
        req.assigned_to_user = new_assignee
        prev_label = (previous.name or previous.email) if previous else "Unassigned"
        new_label = (
            (new_assignee.name or new_assignee.email) if new_assignee else "Unassigned"
        )
        _log(
            req,
            "assignment_changed",
            note=f"Assignment changed: {prev_label} → {new_label}",
        )
        notif_targets = []
        if new_assignee and new_assignee.id != current_user.id:
            notif_targets.append(new_assignee)
        if req.created_by_user_id and req.created_by_user_id != current_user.id:
            creator = db.session.get(User, req.created_by_user_id)
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
        any_changed = True
    if any_changed:
        db.session.commit()
        flash("Bucket assignments updated.", "success")
        try:
            for req in requests:
                record_process_metric_event(
                    req,
                    event_type="assignment_changed",
                    actor_user=current_user,
                    actor_department=getattr(current_user, "department", None),
                    metadata={"bucket_id": bucket_id},
                )
            metrics_module.assignment_changes_total.labels(
                dept=dept, action="assigned" if new_assignee else "cleared"
            ).inc()
            metrics_module.update_owner_gauge(db.session, ReqModel)
        except Exception:
            current_app.logger.exception("Failed to update metrics on bulk assignment")
    else:
        flash("No assignments changed.", "info")

    return redirect(url_for("requests.dashboard", bucket_id=bucket_id))


@requests_bp.route("/search")
@login_required
@cached_view(timeout=30, prefix="search")
def search_requests():
    q = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "").strip().upper()
    priority_filter = (request.args.get("priority") or "").strip().lower()
    sla_filter = (request.args.get("sla") or "").strip().lower()
    approval_only = (request.args.get("approval_only") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    dept = current_user.department
    base = ReqModel.query
    if dept == "A":
        base = base.filter(ReqModel.created_by_user_id == current_user.id)
    elif dept == "B":
        base = base.filter(ReqModel.owner_department == "B")
    else:
        base = base.filter(
            ReqModel.status.in_(
                [
                    "PENDING_C_REVIEW",
                    "C_NEEDS_CHANGES",
                    "C_APPROVED",
                    "B_FINAL_REVIEW",
                    "SENT_TO_A",
                    "CLOSED",
                ]
            )
        )

    results = []
    has_filters = bool(
        q or status_filter or priority_filter or sla_filter or approval_only
    )
    if has_filters:
        # Numeric queries should match request id exactly, but also look for text in other fields
        qry = base.outerjoin(Artifact, Artifact.request_id == ReqModel.id)
        qry = qry.outerjoin(
            Submission,
            and_(
                Submission.request_id == ReqModel.id,
                Submission.is_public_to_submitter == True,
            ),
        )

        if q:
            filters = [
                ReqModel.title.ilike(f"%{q}%"),
                ReqModel.description.ilike(f"%{q}%"),
                Artifact.donor_part_number.ilike(f"%{q}%"),
                Artifact.target_part_number.ilike(f"%{q}%"),
                Artifact.instructions_url.ilike(f"%{q}%"),
                Submission.summary.ilike(f"%{q}%"),
                Submission.details.ilike(f"%{q}%"),
                ReqModel.request_type.ilike(f"%{q}%"),
                ReqModel.pricebook_status.ilike(f"%{q}%"),
                ReqModel.sales_list_reference.ilike(f"%{q}%"),
            ]
            if q.isdigit():
                id_filter = ReqModel.id == int(q)
                qry = qry.filter(or_(id_filter, *filters))
            else:
                qry = qry.filter(or_(*filters))

        if status_filter:
            qry = qry.filter(ReqModel.status == status_filter)
        if priority_filter:
            qry = qry.filter(ReqModel.priority == priority_filter)
        if approval_only:
            approval_statuses = _approval_status_codes()
            qry = qry.filter(
                or_(
                    ReqModel.status.in_(approval_statuses),
                    ReqModel.id.in_(
                        db.session.query(RequestApproval.request_id).distinct()
                    ),
                )
            )

        results = qry.order_by(ReqModel.updated_at.desc()).all()

        now = datetime.utcnow()
        annotated = []
        for req in results:
            req.sla_state = _sla_state_for_request(req, now)
            if sla_filter and req.sla_state != sla_filter:
                continue
            annotated.append(req)
        results = annotated

    # If query is blank, return an empty result set instead of causing an error
    return render_template(
        "search.html",
        results=results,
        q=q,
        status_filter=status_filter,
        priority_filter=priority_filter,
        sla_filter=sla_filter,
        approval_only=approval_only,
        saved_views=_saved_views_for_current_user(),
    )


@requests_bp.route("/search/saved", methods=["POST"])
@login_required
def save_search_view():
    name = (request.form.get("name") or "").strip()
    params = _normalized_saved_view_params(request.form)

    if not name:
        flash("Provide a name for the saved view.", "warning")
        return redirect(url_for("requests.search_requests", **params))
    if not params:
        flash("Choose at least one filter before saving a view.", "warning")
        return redirect(url_for("requests.search_requests"))

    saved = SavedSearchView.query.filter_by(user_id=current_user.id, name=name).first()
    if not saved:
        saved = SavedSearchView(
            user_id=current_user.id,
            tenant_id=getattr(current_user, "tenant_id", None),
            name=name,
            endpoint="requests.search_requests",
        )
        db.session.add(saved)
    saved.params = params
    saved.last_used_at = datetime.utcnow()
    db.session.commit()

    flash(f"Saved view '{name}' updated.", "success")
    return redirect(url_for("requests.search_requests", **params))


@requests_bp.route("/search/saved/<int:view_id>")
@login_required
def open_saved_search_view(view_id: int):
    saved = get_or_404(SavedSearchView, view_id)
    if saved.user_id != current_user.id:
        abort(403)
    saved.last_used_at = datetime.utcnow()
    db.session.add(saved)
    db.session.commit()
    return redirect(url_for("requests.search_requests", **saved.params))


@requests_bp.route("/search/saved/<int:view_id>/delete", methods=["POST"])
@login_required
def delete_saved_search_view(view_id: int):
    saved = get_or_404(SavedSearchView, view_id)
    if saved.user_id != current_user.id:
        abort(403)
    db.session.delete(saved)
    db.session.commit()
    flash("Saved view removed.", "success")
    return redirect(url_for("requests.search_requests"))


@requests_bp.route("/search/saved/<int:view_id>/default", methods=["POST"])
@login_required
def set_default_saved_search_view(view_id: int):
    saved = get_or_404(SavedSearchView, view_id)
    if saved.user_id != current_user.id:
        abort(403)
    SavedSearchView.query.filter_by(user_id=current_user.id).update(
        {SavedSearchView.is_default: False}, synchronize_session=False
    )
    saved.is_default = True
    saved.last_used_at = datetime.utcnow()
    db.session.add(saved)
    db.session.commit()
    flash(f"'{saved.name}' is now your default dashboard shortcut.", "success")
    return redirect(url_for("requests.search_requests", **saved.params))


@requests_bp.route("/requests/bulk_update", methods=["POST"])
@login_required
def bulk_update_requests():
    if not getattr(current_user, "is_admin", False):
        abort(403)

    raw_ids = request.form.getlist("request_ids")
    request_ids = [int(value) for value in raw_ids if str(value).isdigit()]
    new_priority = (request.form.get("priority") or "").strip().lower()

    redirect_kwargs = {
        "q": request.form.get("q", ""),
        "status": request.form.get("status", ""),
        "priority": request.form.get("priority_filter", ""),
        "sla": request.form.get("sla", ""),
    }
    if request.form.get("approval_only"):
        redirect_kwargs["approval_only"] = "1"

    if not request_ids:
        flash("Select at least one request for a bulk update.", "warning")
        return redirect(url_for("requests.search_requests", **redirect_kwargs))

    if new_priority not in {"low", "medium", "high"}:
        flash("Choose a valid priority before running the bulk update.", "warning")
        return redirect(url_for("requests.search_requests", **redirect_kwargs))

    requests_to_update = ReqModel.query.filter(ReqModel.id.in_(request_ids)).all()
    updated = 0
    for req in requests_to_update:
        if not can_view_request(req):
            continue
        if req.priority == new_priority:
            continue
        old_priority = req.priority
        req.priority = new_priority
        _log(
            req,
            "bulk_priority_update",
            note=f"Priority changed from {old_priority} to {new_priority} via search.",
        )
        updated += 1

    db.session.commit()
    flash(
        f"Updated priority on {updated} request{'s' if updated != 1 else ''}.",
        "success",
    )
    return redirect(url_for("requests.search_requests", **redirect_kwargs))


@requests_bp.route("/metrics/ui")
@login_required
@cached_view(timeout=60, prefix="metrics_ui")
def metrics_ui():
    """DB-backed metrics UI with department flow and user-efficiency summaries."""
    allowed_depts = _require_metrics_access(current_user)
    # Accept a `range` parameter: daily, weekly, monthly, yearly (defaults to weekly)
    r = (request.args.get("range") or "weekly").lower()
    selected_dept = (request.args.get("dept") or "").strip().upper()
    visible_depts = [selected_dept] if selected_dept in allowed_depts else allowed_depts
    q = (request.args.get("q") or "").strip()

    # optional user filtering; multiple values may be supplied
    user_filters = request.args.getlist("user")

    snapshot = build_process_metrics_summary(range_key=r, depts=visible_depts, query=q)

    # if user filters were provided, narrow the user list
    if user_filters:
        # allow filtering by id (string of int) or exact email
        filtered = []
        for u in snapshot.get("users", []):
            if str(u.get("user_id")) in user_filters or u.get("email") in user_filters:
                filtered.append(u)
        snapshot["users"] = filtered

    # compute available users from snapshot for UI selection
    available_users = snapshot.get("users", []) if not user_filters else []
    # if filtering was applied we still want to show all possible users so
    # admins can change filters; rebuild from unfiltered summary if needed
    if user_filters:
        # rebuild unfiltered snapshot to list all users
        unfiltered = build_process_metrics_summary(
            range_key=r, depts=visible_depts, query=q
        )
        available_users = unfiltered.get("users", [])

    # export support
    if request.args.get("export") == "csv":
        # compile department summary into CSV
        rows = [
            [
                "Department",
                "Total",
                "Open",
                "Created",
                "Closed",
                "Tracked events",
                "Avg completion (h)",
                "On target %",
            ]
        ]
        for m in snapshot["by_dept"]:
            rows.append(
                [
                    m["dept"],
                    m["total"],
                    m["open"],
                    m["created_window"],
                    m["closed_window"],
                    m["tracked_events"],
                    (
                        m["avg_completion_hours"]
                        if m["avg_completion_hours"] is not None
                        else ""
                    ),
                    (
                        m["within_target_pct"]
                        if m["within_target_pct"] is not None
                        else ""
                    ),
                ]
            )
        # also include user-level breakdown and interactions for a full export
        # users section (always output headers so readers know structure)
        rows.append([])
        rows.append(
            [
                "Users",
                "Department",
                "Events",
                "Status changes",
                "Assignments",
                "Slow events",
                "Avg gap (h)",
                "Avg completion (h)",
                "Closed count",
            ]
        )
        for u in snapshot.get("users", []):
            rows.append(
                [
                    u.get("email") or "",
                    u.get("department") or "",
                    u.get("events"),
                    u.get("status_changes"),
                    u.get("assignments"),
                    u.get("slow_events"),
                    (
                        u.get("avg_gap_hours")
                        if u.get("avg_gap_hours") is not None
                        else ""
                    ),
                    (
                        u.get("avg_completion_hours")
                        if u.get("avg_completion_hours") is not None
                        else ""
                    ),
                    u.get("closed_count"),
                ]
            )
        # interactions section
        rows.append([])
        rows.append(
            [
                "From dept",
                "To dept",
                "Count",
            ]
        )
        for i in snapshot.get("interactions", []):
            rows.append(
                [
                    i.get("from_department"),
                    i.get("to_department"),
                    i.get("count"),
                ]
            )
        output = []
        for rrow in rows:
            # ensure proper quoting if any commas in text? simple join is ok for now
            output.append(",".join(str(x) for x in rrow))
        return Response("\n".join(output), content_type="text/csv")

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
                    if (row.get("from_department") == dept_code)
                    or (row.get("to_department") == dept_code)
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
        q=q,
        user_filters=user_filters,
        available_users=available_users,
        metrics_view_endpoint="requests.metrics_ui",
    )


@requests_bp.route("/metrics")
def metrics():
    """Prometheus metrics exposition endpoint."""
    try:
        payload, content_type = metrics_module.metrics_output()
        return Response(payload, content_type=content_type)
    except Exception:
        current_app.logger.exception("Failed to generate Prometheus metrics")
        abort(500)


@requests_bp.route("/metrics/json")
@login_required
def metrics_json():
    _require_metrics_access(current_user)
    """Machine-friendly JSON metrics for external integrations."""
    try:
        allowed_depts = _metric_departments_for_user(current_user)
        selected_dept = (request.args.get("dept") or "").strip().upper()
        r = (request.args.get("range") or "weekly").lower()
        q = (request.args.get("q") or "").strip()
        visible_depts = (
            [selected_dept] if selected_dept in allowed_depts else allowed_depts
        )
        user_filters = request.args.getlist("user")
        snapshot = build_process_metrics_summary(
            range_key=r, depts=visible_depts, query=q
        )

        if user_filters:
            filtered = []
            for u in snapshot.get("users", []):
                if (
                    str(u.get("user_id")) in user_filters
                    or u.get("email") in user_filters
                ):
                    filtered.append(u)
            snapshot["users"] = filtered

        payload = {
            "now": snapshot["now"].isoformat() + "Z",
            "cutoff": snapshot["cutoff"].isoformat() + "Z",
            "range": snapshot["range_key"],
            "summary": snapshot["summary"],
            "by_dept": {row["dept"]: row for row in snapshot["by_dept"]},
            "users": snapshot["users"],
            "interactions": snapshot["interactions"],
            "allowed_departments": allowed_depts,
        }
        return jsonify(payload)
    except Exception:
        current_app.logger.exception("Failed to render JSON metrics")
        abort(500)


@requests_bp.route("/requests/<int:request_id>")
@login_required
def request_detail(request_id: int):
    # Use an explicit, session-bound query to ensure the `Request` instance
    # is attached to the current session and related objects are eager-loaded
    # to avoid DetachedInstanceError during attribute access after flush/commit.
    try:
        req = (
            db.session.query(ReqModel)
            .options(
                selectinload(ReqModel.assigned_to_user),
                selectinload(ReqModel.artifacts),
            )
            .filter(ReqModel.id == request_id)
            .one()
        )
    except Exception:
        # Fallback to get_or_404 which includes rollback handling
        req = get_or_404(ReqModel, request_id)
    try:
        if not can_view_request(req):
            abort(403)
    except Exception:
        # If the `req` instance appears detached during permission checks,
        # attempt a fresh query and proceed. Log the exception for diagnostics.
        try:
            import traceback

            traceback.print_exc()
        except Exception:
            pass
        try:
            req = (
                db.session.query(ReqModel)
                .options(
                    selectinload(ReqModel.assigned_to_user),
                    selectinload(ReqModel.artifacts),
                )
                .filter(ReqModel.id == request_id)
                .one()
            )
        except Exception:
            req = get_or_404(ReqModel, request_id)
        if not can_view_request(req):
            abort(403)

    # Pre-declare template variables to satisfy static analysis and
    # ensure they exist even if early returns occur.
    #
    # These defaults are intentionally minimal and neutral. They allow
    # rendering `request_detail.html` from alternative flows (for
    # example the dynamic `request_new` POST path) without requiring the
    # full view-preparation logic to have executed. Integrations that
    # populate these values later should overwrite them before rendering.
    comments = []
    submissions = []
    audit = []
    comment_form = None
    artifact_form = None
    transition_form = None
    toggle_form = None
    request_edit_form = None
    donor_form = None
    assignment_form = None
    has_part_number = False
    has_instructions = False
    next_hint = None
    image_attachments = []
    can_reject_request = False
    reject_button_label = ""
    reject_message = ""
    status_options_map = {}

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
    # Initialize commonly used template variables early so that branches which
    # return/render the detail template before full view preparation won't
    # reference names that are assigned later in this function (fixes
    # static-analysis warnings and prevents UnboundLocalError at runtime).
    comments = []
    submissions = []
    audit = []
    try:
        comment_form = CommentForm()
    except Exception:
        comment_form = None
    try:
        artifact_form = ArtifactForm()
    except Exception:
        artifact_form = None
    try:
        transition_form = TransitionForm()
    except Exception:
        transition_form = None
    try:
        toggle_form = ToggleCReviewForm()
    except Exception:
        toggle_form = None
    try:
        request_edit_form = RequestArtifactEditForm()
    except Exception:
        request_edit_form = None
    try:
        donor_form = DonorOnlyForm()
    except Exception:
        donor_form = None
    try:
        assignment_form = AssignmentForm()
    except Exception:
        assignment_form = None
    has_part_number = False
    has_instructions = False
    image_attachments = []
    can_reject_request = False
    reject_button_label = ""
    reject_message = ""
    status_options_map = {}
    allowed_scopes = visible_comment_scopes_for_user()
    comments = (
        Comment.query.filter_by(request_id=req.id)
        .order_by(Comment.created_at.asc())
        .all()
    )
    comments = [c for c in comments if c.visibility_scope in allowed_scopes]

    comment_form = CommentForm()
    comment_form.visibility_scope.choices = [
        (s, s.replace("_", " ").title()) for s in allowed_comment_scopes_for_user()
    ]

    artifact_form = ArtifactForm()

    transition_form = TransitionForm()
    dept = current_user.department
    # Use active Workflow spec (if present) to compute allowed transitions and labels.
    from .workflow import allowed_transition_routes, allowed_transitions_with_labels

    if dept == "A":
        # Dept A has a constrained set: prefer workflow-defined choices but
        # keep the small set of actions available to Dept A (reopen/close).
        choices = []
        label_map = {
            "B_IN_PROGRESS": "Request review from Department B",
            "CLOSED": "Close ticket",
        }
        if req.status == "SENT_TO_A":
            for to in ("B_IN_PROGRESS", "CLOSED"):
                if is_transition_valid_for_request(req, dept, req.status, to):
                    choices.append((to, label_map[to]))
        elif req.status == "CLOSED":
            if _closed_within_hours(req, hours=48) and is_transition_valid_for_request(
                req, dept, req.status, "B_IN_PROGRESS"
            ):
                choices.append(("B_IN_PROGRESS", label_map["B_IN_PROGRESS"]))
        transition_form.to_status.choices = choices
    elif dept == "B":
        # For Dept B, consult the workflow helper which prefers a dept-scoped
        # workflow then global; fall back to legacy allowed transitions.
        choices = allowed_transitions_with_labels(dept, req.status)
        # In some legacy cases we still want WAITING_ON_A_RESPONSE to show a friendlier label
        choices = [
            (
                c,
                (
                    "Pending review from Department A"
                    if c == "WAITING_ON_A_RESPONSE"
                    else l
                ),
            )
            for c, l in choices
        ]
        transition_form.to_status.choices = choices
        transition_form.requires_c_review.data = req.requires_c_review
    else:
        # Dept C: constrained to approvals/changes; still consult workflow spec
        transition_form.to_status.choices = allowed_transitions_with_labels(
            dept, req.status
        )

    transition_routes = allowed_transition_routes(dept, req.status)
    transition_target_choices = []
    seen_transition_targets = set()
    for route in transition_routes:
        target_department = (route.get("to_department") or "").strip().upper()
        if not target_department or target_department in seen_transition_targets:
            continue
        seen_transition_targets.add(target_department)
        transition_target_choices.append(
            (target_department, f"Department {target_department}")
        )
    transition_form.target_department.choices = [
        ("", "-- Choose department --")
    ] + transition_target_choices

    # Keep a local `possible` list for downstream handoff hint logic (legacy name)
    possible = transition_form.to_status.choices

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
    elif (
        current_user.department == "C"
        and req.status == "PENDING_C_REVIEW"
        and req.requires_c_review
    ):
        # Show an assignment UI scoped to Dept C users so they can take ownership
        assignment_form = AssignmentForm()
        assignment_form.assignee.choices = _assignment_choices(current_user.department)
        assignment_form.assignee.data = req.assigned_to_user_id or -1
    elif current_user.department == "A" and req.owner_department == "A":
        # Dept A assignment UI
        assignment_form = AssignmentForm()
        assignment_form.assignee.choices = _assignment_choices(current_user.department)
        assignment_form.assignee.data = req.assigned_to_user_id or -1

    submissions = (
        Submission.query.filter_by(request_id=req.id)
        .order_by(Submission.created_at.asc())
        .all()
    )
    audit = (
        AuditLog.query.filter_by(request_id=req.id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    recent_status_path = _build_recent_status_path(
        [a for a in audit if a.action_type == "status_change"], req.status
    )
    suggested_next_actions = list(possible or [])[:4]
    approval_state = _approval_cycle_state(req.id, req.status, user=current_user)

    # Avoid lazy-loading `req.artifacts` on potentially detached instances;
    # query artifacts directly by request id so the session is used explicitly.
    try:
        has_part_number = (
            Artifact.query.filter_by(
                request_id=req.id, artifact_type="part_number"
            ).count()
            > 0
        )
    except Exception:
        has_part_number = False
    try:
        has_instructions = (
            Artifact.query.filter_by(
                request_id=req.id, artifact_type="instructions"
            ).count()
            > 0
        )
    except Exception:
        has_instructions = False
    # Gather image attachments (screenshots) across submissions for quick viewing
    try:
        allowed = current_app.config.get("ALLOWED_IMAGE_MIMES", [])
        image_attachments = (
            Attachment.query.join(Submission)
            .filter(Submission.request_id == req.id)
            .filter(Attachment.content_type.in_(allowed))
            .order_by(Attachment.created_at.desc())
            .all()
        )
    except Exception:
        image_attachments = []

    # Reject-request feature config (assignee-only action; dept-specific toggle)
    reject_cfg = None
    # Safe default per requirement: Dept B enabled by default.
    reject_enabled_here = current_user.department == "B"
    reject_button_label = "Reject Request"
    reject_message = None
    try:
        reject_cfg = RejectRequestConfig.get()
        reject_button_label = (
            reject_cfg.button_label or "Reject Request"
        ).strip() or "Reject Request"
        reject_message = reject_cfg.rejection_message
        reject_enabled_here = bool(
            reject_cfg.enabled
        ) and reject_cfg.enabled_for_department(current_user.department)
    except Exception:
        # Keep default behavior when config storage is unavailable.
        reject_enabled_here = current_user.department == "B"

    can_reject_request = bool(
        reject_enabled_here
        and req.status != "CLOSED"
        and req.assigned_to_user_id
        and req.assigned_to_user_id == current_user.id
    )
    # Prepare status option flags for client-side UI
    try:
        from ..models import StatusOption

        status_options_map = {
            s.code: bool(s.screenshot_required) for s in StatusOption.query.all()
        }
    except Exception:
        status_options_map = {}

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
        assigned_user=(
            db.session.get(User, req.assigned_to_user_id)
            if req.assigned_to_user_id
            else None
        ),
        handoff_targets=[
            t for t, _ in possible if handoff_for_transition(req.status, t)
        ],
        transition_routes=transition_routes,
        recent_status_path=recent_status_path,
        suggested_next_actions=suggested_next_actions,
        approval_state=approval_state,
        image_attachments=image_attachments,
        can_reject_request=can_reject_request,
        reject_button_label=reject_button_label,
        reject_message=reject_message,
        status_options_map=status_options_map,
        can_change_priority=_user_can_change_priority(current_user, req),
    )


@requests_bp.route(
    "/requests/<int:request_id>/approvals/<int:approval_id>/decision", methods=["POST"]
)
@login_required
def record_approval_decision(request_id: int, approval_id: int):
    req = get_or_404(ReqModel, request_id)
    if not can_view_request(req):
        abort(403)

    approval = get_or_404(RequestApproval, approval_id)
    if approval.request_id != req.id:
        abort(404)
    if req.status != approval.status_code:
        flash(
            "This approval stage is no longer active for the current request status.",
            "warning",
        )
        return redirect(url_for("requests.request_detail", request_id=request_id))

    cycle_rows = _current_approval_rows(req.id, approval.status_code)
    if not _user_can_signoff_approval(approval, current_user, cycle_rows):
        abort(403)

    decision = (request.form.get("decision") or "approve").strip().lower()
    if decision not in {"approve", "changes_requested"}:
        decision = "approve"
    note = (request.form.get("note") or "").strip() or None

    approval.state = "approved" if decision == "approve" else "changes_requested"
    approval.decision_note = note
    approval.decided_by_user_id = current_user.id
    approval.decided_at = datetime.utcnow()

    outcome_label = "approved" if decision == "approve" else "requested changes for"
    _log(
        req,
        "approval_decision",
        note=f"{current_user.email} {outcome_label} stage {approval.stage_order}: {approval.stage_name}",
        from_status=req.status,
        to_status=req.status,
    )
    db.session.commit()

    flash(
        "Approval recorded." if decision == "approve" else "Change request recorded.",
        "success",
    )
    return redirect(url_for("requests.request_detail", request_id=request_id))


@requests_bp.route("/requests/<int:request_id>/assign_self", methods=["POST"])
@login_required
def assign_self(request_id: int):
    req = get_or_404(ReqModel, request_id)
    if current_user.department not in ("A", "B", "C"):
        abort(403)
    if not can_view_request(req):
        abort(403)

    if req.status == "CLOSED":
        flash("Cannot assign a closed request.", "warning")
        return redirect(url_for("requests.request_detail", request_id=request_id))

    # Enforce: Department A users may not self-assign a request until it
    # has been processed by Department B and explicitly sent back to A.
    # Allow if the request is already owned by A (owner_department == 'A')
    # or if there's a recorded Submission from B -> A.
    if current_user.department == "A" and not (
        req.owner_department == "A" or _was_sent_back_to_a(req)
    ):
        flash(
            "Department A may only assign requests to themselves after Dept B has processed and returned the request.",
            "warning",
        )
        return redirect(url_for("requests.request_detail", request_id=request_id))

    if req.assigned_to_user_id and req.assigned_to_user_id != current_user.id:
        flash("This request is already assigned.", "warning")
        return redirect(url_for("requests.request_detail", request_id=request_id))

    # Enforce: a user may only have one active assigned request at a time.
    existing = (
        ReqModel.query.filter(
            ReqModel.assigned_to_user_id == current_user.id,
            ReqModel.id != req.id,
            ReqModel.status != "CLOSED",
            ReqModel.is_denied == False,
        )
        .order_by(ReqModel.created_at.asc())
        .first()
    )
    if existing:
        flash(
            f"You are already assigned to Request #{existing.id}. Complete or clear that assignment before taking another.",
            "warning",
        )
        return redirect(url_for("requests.request_detail", request_id=request_id))

    req.assigned_to_user_id = current_user.id

    _log(req, "assignment_changed", note=f"Assigned to {current_user.email}")

    # Notify the original submitter if they are an internal user
    if req.created_by_user_id:
        assignee_label = current_user.name or current_user.email
        db.session.add(
            Notification(
                user_id=req.created_by_user_id,
                request_id=req.id,
                type="assignment",
                title="Assignment update",
                body=f"{assignee_label} is assigned to your request.",
                url=url_for("requests.request_detail", request_id=req.id),
            )
        )
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
        metrics_module.assignment_changes_total.labels(
            dept=current_user.department, action="assigned"
        ).inc()
        metrics_module.update_owner_gauge(db.session, ReqModel)
        record_process_metric_event(
            req,
            event_type="assignment_changed",
            actor_user=current_user,
            actor_department=getattr(current_user, "department", None),
            to_status=req.status,
            metadata={"assignment_action": "assigned_to_self"},
        )
    except Exception:
        current_app.logger.exception("Failed to update metrics on assignment")

    flash("Assigned to you.", "success")
    return redirect(url_for("requests.request_detail", request_id=request_id))


@requests_bp.route("/requests/<int:request_id>/reject", methods=["POST"])
@login_required
def reject_request(request_id: int):
    req = get_or_404(ReqModel, request_id)
    if not can_view_request(req):
        abort(403)

    rv = _require_assigned_user(req)
    if rv:
        return rv

    cfg = None
    try:
        cfg = RejectRequestConfig.get()
    except Exception:
        cfg = None

    enabled_for_dept = current_user.department == "B"
    if cfg is not None:
        enabled_for_dept = bool(cfg.enabled) and cfg.enabled_for_department(
            current_user.department
        )

    if not enabled_for_dept:
        flash("Reject request is disabled for your department.", "warning")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    if req.status == "CLOSED":
        flash("Request is already closed.", "warning")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    reason = (request.form.get("reject_reason") or "").strip()
    if not reason:
        flash("A rejection reason is required.", "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    message = "This request was rejected."
    if cfg is not None and cfg.rejection_message:
        message = cfg.rejection_message.strip() or message
    comment_body = f"{message}\n\nReason: {reason}"

    db.session.add(
        Comment(
            request_id=req.id,
            author_type="user",
            author_user_id=current_user.id,
            visibility_scope="public",
            body=comment_body,
        )
    )

    from_status = req.status
    req.status = "CLOSED"
    req.owner_department = owner_for_status("CLOSED")
    req.assigned_to_user = None

    _log(
        req,
        "status_change",
        note=f"Request rejected by {current_user.email}. Reason: {reason}",
        from_status=from_status,
        to_status="CLOSED",
    )

    recipients = []
    if (
        req.created_by_user
        and req.created_by_user.is_active
        and req.created_by_user.id != current_user.id
    ):
        recipients.append(req.created_by_user)

    if recipients:
        notify_users(
            recipients,
            title=f"Request #{req.id} rejected",
            body=comment_body,
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="status_change",
            request_id=req.id,
        )

    db.session.commit()
    flash("Request rejected and closed.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))


def _collect_nudge_targets(req, exclude_user_id=None):
    assigned_target = None
    if req.assigned_to_user_id:
        u = db.session.get(User, req.assigned_to_user_id)
        if u and getattr(u, "is_active", False):
            assigned_target = u

    if assigned_target and assigned_target.id != exclude_user_id:
        recipients = [assigned_target]
    else:
        try:
            recipients = users_in_department(req.owner_department)
        except Exception:
            recipients = []

    if exclude_user_id:
        recipients = [
            u for u in recipients if getattr(u, "id", None) != exclude_user_id
        ]

    deduped = {
        getattr(u, "id", None): u
        for u in recipients
        if getattr(u, "id", None) is not None
    }
    return list(deduped.values())


def _user_can_change_priority(user, req) -> bool:
    """Return True if ``user`` may adjust the priority of ``req``.

    Admin users always may; department editors require the `can_change_priority`
    flag for the request's owner department.
    """
    if getattr(user, "is_admin", False):
        return True
    try:
        de = DepartmentEditor.query.filter_by(
            user_id=user.id, department=req.owner_department
        ).first()
        if de and getattr(de, "can_change_priority", False):
            return True
    except Exception:
        pass
    return False


def _dispatch_nudge_notifications(
    req,
    targets,
    *,
    dedupe_prefix,
    title,
    body,
    email_subject=None,
    email_body=None,
    link=None,
    actor_user_id=None,
):
    if not targets:
        return
    if link is None:
        link = url_for("requests.request_detail", request_id=req.id, _external=False)
    dedupe_key = f"{dedupe_prefix}:req_{req.id}"
    deduped = {
        getattr(u, "id", None): u for u in targets if getattr(u, "id", None) is not None
    }
    for u in deduped.values():
        try:
            db.session.add(
                Notification(
                    user_id=u.id,
                    request_id=req.id,
                    type="nudge",
                    title=title,
                    body=body,
                    url=link,
                    dedupe_key=dedupe_key,
                    actor_user_id=actor_user_id,
                )
            )
            if email_subject and email_body and getattr(u, "email", None):
                recipients_map = {u.email: u.id}
                try:
                    notifications_module._send_emails_async(
                        recipients_map,
                        email_subject,
                        email_body,
                        html=None,
                        request_id=req.id,
                    )
                except Exception:
                    try:
                        current_app.logger.exception(
                            "Failed to queue nudge email for user %s", u.id
                        )
                    except Exception:
                        pass
        except Exception:
            try:
                current_app.logger.exception("Failed to create nudge notification")
            except Exception:
                pass
    try:
        db.session.commit()
    except Exception:
        try:
            current_app.logger.exception("Failed to commit nudge notifications")
        except Exception:
            pass


@requests_bp.route(
    "/requests/<int:request_id>/admin_reminder",
    methods=["POST"],
    endpoint="admin_reminder",
)
@requests_bp.route("/requests/<int:request_id>/admin_nudge", methods=["POST"])
@login_required
def admin_nudge(request_id: int):
    """Admin-only debug endpoint: trigger a 30s admin reminder for a request.

    This creates in-app `Notification` rows for the assignee (or all users in
    the owner department) and attempts to send email notifications in the
    background. Visible only to admin users.
    """
    if not getattr(current_user, "is_admin", False):
        abort(403)

    req = get_or_404(ReqModel, request_id)
    if not can_view_request(req):
        abort(403)

    targets = _collect_nudge_targets(req)
    if not targets:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return (
                jsonify({"ok": False, "message": "No recipients found for reminder."}),
                400,
            )
        flash("No recipients found for reminder.", "warning")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    link = url_for("requests.request_detail", request_id=req.id, _external=False)
    _dispatch_nudge_notifications(
        req,
        targets,
        dedupe_prefix="admin_nudge",
        title=f"Admin reminder: Request #{req.id}",
        body=f"Admin triggered reminder for request #{req.id}.",
        email_subject=f"Admin reminder: Request #{req.id} still open",
        email_body=f"An administrator triggered a reminder for request #{req.id} ({req.title}).\n\n{link}",
        link=link,
    )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "message": "Admin reminder sent."}), 200
    flash("Admin reminder sent.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route(
    "/requests/<int:request_id>/push_reminder",
    methods=["POST"],
    endpoint="push_reminder",
)
@requests_bp.route("/requests/<int:request_id>/push_nudge", methods=["POST"])
@login_required
def push_nudge(request_id: int):
    flags = FeatureFlags.get()
    if not getattr(flags, "allow_user_nudges", False):
        abort(403)

    # enforce per-day sending limit for the current user
    if getattr(current_user, "daily_nudge_limit", 1):
        from datetime import datetime, timedelta

        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        sent_today = (
            Notification.query.filter_by(actor_user_id=current_user.id, type="nudge")
            .filter(Notification.created_at >= today_start)
            .count()
        )
        if sent_today >= current_user.daily_nudge_limit:
            flash("You have reached your daily reminder limit.", "warning")
            return redirect(url_for("requests.request_detail", request_id=request_id))

    req = get_or_404(ReqModel, request_id)
    if not can_view_request(req):
        abort(403)

    targets = _collect_nudge_targets(req, exclude_user_id=current_user.id)
    if not targets:
        flash("No recipients found for reminder.", "warning")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    link = url_for("requests.request_detail", request_id=req.id, _external=False)
    actor_label = current_user.name or current_user.email or "A teammate"
    title = f"Reminder requested: Request #{req.id}"
    body = f"{actor_label} requested a reminder for request #{req.id}."
    text_body = f"{actor_label} requested a reminder for request #{req.id} ({req.title}).\n\n{link}"
    _dispatch_nudge_notifications(
        req,
        targets,
        dedupe_prefix="user_nudge",
        title=title,
        body=body,
        email_subject=title,
        email_body=text_body,
        link=link,
        actor_user_id=getattr(current_user, "id", None),
    )

    flash("Reminder sent to the current owner(s).", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route("/requests/<int:request_id>/change_priority", methods=["POST"])
@login_required
def change_priority(request_id: int):
    req = get_or_404(ReqModel, request_id)
    if not can_view_request(req):
        abort(403)
    if not _user_can_change_priority(current_user, req):
        abort(403)
    new_priority = (request.form.get("priority") or "").strip().lower()
    if new_priority not in {"low", "medium", "high", "highest"}:
        flash("Invalid priority.", "warning")
        return redirect(url_for("requests.request_detail", request_id=req.id))
    if req.priority != new_priority:
        old = req.priority
        req.priority = new_priority
        _log(
            req,
            "priority_change",
            note=f"{current_user.email or current_user.name} changed priority from {old} to {new_priority}",
        )
        db.session.commit()
        flash("Priority updated.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route(
    "/admin/workflows/<int:workflow_id>/reset_requests", methods=["POST"]
)
@login_required
def reset_workflow_requests(workflow_id: int):
    """Admin-only: delete all requests belonging to the given workflow.

    This action is destructive and requires an admin account. The caller may
    include a `ref_request_id` form field to redirect back to a request detail
    page after completion.
    """
    if not getattr(current_user, "is_admin", False):
        abort(403)

    from ..models import Workflow

    wf = db.session.get(Workflow, workflow_id)
    if not wf:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": "Workflow not found"}), 404
        flash("Workflow not found.", "warning")
        return redirect(url_for("requests.request_list"))

    refs = ReqModel.query.filter_by(workflow_id=workflow_id).all()
    count = len(refs)
    if count == 0:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": True, "message": "No requests to delete"}), 200
        flash("No requests to delete for this workflow.", "info")
        ref_id = request.form.get("ref_request_id")
        if ref_id:
            return redirect(url_for("requests.request_detail", request_id=ref_id))
        return redirect(url_for("requests.request_list"))

    try:
        for r in refs:
            db.session.delete(r)
        db.session.commit()
        msg = f"Deleted {count} requests for workflow '{wf.name or wf.id}'."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": True, "message": msg}), 200
        flash(msg, "success")
    except Exception:
        db.session.rollback()
        try:
            current_app.logger.exception("Failed to reset workflow requests")
        except Exception:
            pass
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": "Failed to reset requests"}), 500
        flash("Failed to reset workflow requests.", "danger")

    ref_id = request.form.get("ref_request_id")
    if ref_id:
        return redirect(url_for("requests.request_detail", request_id=ref_id))
    return redirect(url_for("requests.request_list"))


def _clean_presence():
    cutoff = time.time() - 70
    for rid in list(_presence.keys()):
        _presence[rid] = {
            uid: info
            for uid, info in _presence[rid].items()
            if info.get("ts", 0) >= cutoff
        }
        if not _presence[rid]:
            _presence.pop(rid, None)


def _was_sent_back_to_a(req: ReqModel) -> bool:
    """Return True if this request has been handed back from Dept B to Dept A.

    This is used to prevent the original Dept A submitter from assigning
    themselves to their own request until it has been processed by Dept B
    and explicitly returned to Dept A.
    """
    return (
        Submission.query.filter_by(
            request_id=req.id, from_department="B", to_department="A"
        ).count()
        > 0
    )


@requests_bp.route("/requests/<int:request_id>/presence", methods=["GET", "POST"])
@login_required
def request_presence(request_id: int):
    req = get_or_404(ReqModel, request_id)
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
    a = get_or_404(Artifact, artifact_id)
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
    _log(
        req,
        "edit_requested",
        note=f"Dept {current_user.department} requested edit: {note}",
    )

    # Determine which department should be notified: prefer the artifact creator dept (if present)
    target_dept = a.created_by_department or req.owner_department
    try:
        notify_users(
            users_in_department(target_dept),
            title=f"Edit requested on Request #{req.id}",
            body=(
                f"{current_user.department} requested an artifact edit: {note}"
                if note
                else f"{current_user.department} requested an artifact edit."
            ),
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="edit_requested",
            request_id=req.id,
        )
    except Exception:
        current_app.logger.exception("Failed to notify users about edit request")

    db.session.commit()
    flash("Edit request sent.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route(
    "/requests/<int:request_id>/verification-placeholder", methods=["POST"]
)
@login_required
def store_verification_placeholder(request_id: int):
    # Temporary logging endpoint; once integration is available, this should look up the method/part in the source system before persisting.
    req = get_or_404(ReqModel, request_id)
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
            note_lines.append(
                f"Method verification: FAILED ({vm.get('reason') or vm.get('error')})"
            )
        else:
            note_lines.append("Method verification: not configured")

    if created_part:
        vp = verifier.verify_part_number(created_part)
        ver_results.append(("part", created_part, vp))
        if vp.get("ok") is True:
            note_lines.append(f"Part verification: OK")
        elif vp.get("ok") is False:
            note_lines.append(
                f"Part verification: FAILED ({vp.get('reason') or vp.get('error')})"
            )
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
    req = get_or_404(ReqModel, request_id)
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
        creator = db.session.get(User, req.created_by_user_id)
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

    mentioned_users = _mentioned_recipients_for_comment(req, c.body)
    if mentioned_users:
        notify_users(
            mentioned_users,
            title=f"You were mentioned on Request #{req.id}",
            body=(c.body[:160] + "…") if len(c.body) > 160 else c.body,
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="mention",
            request_id=req.id,
            allow_email=False,
        )

    _log(req, "comment_added", note=f"Comment added ({c.visibility_scope}).")
    db.session.commit()

    flash("Comment added.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route("/artifacts/<int:artifact_id>/set_donor", methods=["POST"])
@login_required
def set_artifact_donor(artifact_id: int):
    a = get_or_404(Artifact, artifact_id)
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
            recipients.extend(users_in_department("C"))
        uniq = {u.id: u for u in recipients}.values()
        notify_users(
            uniq,
            title=f"Donor part number updated on Request #{req.id}",
            body=(
                f"Donor set: {donor} — by {current_user.email}"
                if donor
                else f"Donor cleared by {current_user.email}"
            ),
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
    a = get_or_404(Artifact, artifact_id)
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
            recipients.extend(users_in_department("C"))
        # Deduplicate
        uniq = {u.id: u for u in recipients}.values()
        notify_users(
            uniq,
            title=f"Part number updated on Request #{req.id}",
            body=(
                f"Target part number set: {target} — by {current_user.email}"
                if target
                else f"Target cleared by {current_user.email}"
            ),
            url=url_for("requests.request_detail", request_id=req.id),
            ntype="artifact_target_added",
            request_id=req.id,
        )
    except Exception:
        # notification failures should not block the update
        current_app.logger.exception(
            "Failed to queue notifications for artifact target change"
        )

    db.session.commit()
    return _success_response("Target part number updated.", req)


@requests_bp.route("/artifacts/<int:artifact_id>/edit", methods=["POST"])
@login_required
def edit_artifact(artifact_id: int):
    a = get_or_404(Artifact, artifact_id)
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

    _log(
        req,
        "artifact_edited",
        note=f"Artifact edited by Dept {dept}: {a.artifact_type}",
    )

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
            users.extend(users_in_department("C"))
            uniq = {u.id: u for u in users}.values()
        recipients = [u for u in uniq if u.id != current_user.id]
        if recipients:
            title = f"Artifact updated on Request #{req.id}"
            body = f"{current_user.email} edited the {a.artifact_type} artifact on Request #{req.id}."
            url = url_for("requests.request_detail", request_id=req.id)
            notify_users(
                recipients,
                title=title,
                body=body,
                url=url,
                ntype="artifact_edited",
                request_id=req.id,
            )
    except Exception:
        current_app.logger.exception("Failed to queue artifact edit notifications")

    db.session.commit()
    return _success_response("Artifact updated.", req)


@requests_bp.route("/requests/<int:request_id>/artifact", methods=["POST"])
@login_required
def add_artifact(request_id: int):
    req = get_or_404(ReqModel, request_id)
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
    # Use an explicit, session-bound query to ensure the Request instance
    # is attached to the current session and to eager-load common relations
    # to avoid DetachedInstanceError during attribute access.
    try:
        req = (
            db.session.query(ReqModel)
            .options(
                selectinload(ReqModel.assigned_to_user),
                selectinload(ReqModel.artifacts),
            )
            .filter(ReqModel.id == request_id)
            .one()
        )
    except Exception:
        req = get_or_404(ReqModel, request_id)
    # Permission check: prefer using `can_view_request` but fall back to a
    # safe, session-backed column query when attribute access on `req`
    # triggers DetachedInstanceError (observed in tests when instances are
    # expired/detached). This avoids calling into `req` properties that
    # may require a session to refresh.
    try:
        if not can_view_request(req):
            abort(403)
    except Exception:
        try:
            row = (
                db.session.query(
                    ReqModel.owner_department,
                    ReqModel.created_by_user_id,
                    ReqModel.status,
                )
                .filter(ReqModel.id == request_id)
                .one()
            )
            owner_dept, created_by_user_id, status_val = row
        except Exception:
            abort(403)

        # Reimplement permissive `can_view_request` logic here without touching
        # the detached `req` instance.
        if getattr(current_user, "is_admin", False):
            pass
        else:
            enforce = current_app.config.get("ENFORCE_DEPT_ISOLATION", False)
            if not enforce:
                if current_user.department in ("B", "C"):
                    pass
                elif (
                    created_by_user_id == getattr(current_user, "id", None)
                    or owner_dept == "A"
                ):
                    pass
                else:
                    abort(403)
            else:
                dept = getattr(current_user, "department", None)
                if not dept:
                    abort(403)
                if owner_dept == dept:
                    pass
                else:
                    sent = Submission.query.filter_by(
                        request_id=request_id, to_department=dept
                    ).first()
                    if not sent and not (
                        dept == "C" and status_val == "PENDING_C_REVIEW"
                    ):
                        abort(403)

    form = TransitionForm()
    dept = current_user.department

    from sqlalchemy.orm.exc import DetachedInstanceError

    def _run_transition(req):
        # The main transition logic. Kept as an inner function so we can
        # re-query the `req` instance if a DetachedInstanceError occurs
        # and retry once.
        possible = []

        from .workflow import allowed_transition_routes, allowed_transitions_with_labels

        if dept == "A":
            # Dept A: only reopen or close
            for to in ("B_IN_PROGRESS", "CLOSED"):
                if is_transition_valid_for_request(req, dept, req.status, to):
                    possible.append((to, to))
        elif dept == "B":
            choices = allowed_transitions_with_labels(dept, req.status)
            possible = [
                (
                    code,
                    (
                        "Pending review from Department A"
                        if code == "WAITING_ON_A_RESPONSE"
                        else label
                    ),
                )
                for code, label in choices
            ]
        else:
            # Dept C: only approve or request changes
            possible = allowed_transitions_with_labels(dept, req.status)

        form.to_status.choices = possible
        transition_routes = allowed_transition_routes(dept, req.status)
        target_choices = []
        seen_targets = set()
        for route in transition_routes:
            target_department = (route.get("to_department") or "").strip().upper()
            if not target_department or target_department in seen_targets:
                continue
            seen_targets.add(target_department)
            target_choices.append(
                (target_department, f"Department {target_department}")
            )
        form.target_department.choices = [
            ("", "-- Choose department --")
        ] + target_choices

        if not form.validate_on_submit():
            flash("Transition failed validation.", "danger")
            return redirect(url_for("requests.request_detail", request_id=req.id))

        to_status = form.to_status.data
        selected_target_department = (
            (getattr(form, "target_department", None).data or "").strip().upper()
            if getattr(form, "target_department", None)
            else ""
        ) or None

        matching_routes = [
            route for route in transition_routes if route.get("to_status") == to_status
        ]
        route_target_departments = sorted(
            {
                (route.get("to_department") or "").strip().upper()
                for route in matching_routes
                if (route.get("to_department") or "").strip().upper()
            }
        )
        selected_route = None
        if matching_routes:
            if selected_target_department:
                selected_route = next(
                    (
                        route
                        for route in matching_routes
                        if (route.get("to_department") or "").strip().upper()
                        == selected_target_department
                    ),
                    None,
                )
            if selected_route is None and len(route_target_departments) == 1:
                selected_route = matching_routes[0]
            elif selected_route is None and len(route_target_departments) > 1:
                flash(
                    "Choose which department this request should be sent to.",
                    "warning",
                )
                return redirect(url_for("requests.request_detail", request_id=req.id))

        resolved_target_owner = (
            (selected_route.get("to_department") or "").strip().upper()
            if selected_route and selected_route.get("to_department")
            else (selected_target_department or owner_for_status(to_status))
        )

        if dept == "B":
            req.requires_c_review = bool(form.requires_c_review.data)

            # If the UI requested executive approval and immediate send to A, honor it
            try:
                force_send = hasattr(form, "force_send_to_a") and (
                    str(form.force_send_to_a.data or "").lower() in ("1", "true", "yes")
                )
            except Exception:
                force_send = False

            if force_send and to_status == "EXEC_APPROVAL":
                # Treat this as an immediate send-to-A action
                to_status = "SENT_TO_A"
                flash(
                    "Marked for executive approval — sending to Department A for review.",
                    "info",
                )

            if req.requires_c_review and to_status in (
                "B_IN_PROGRESS",
                "WAITING_ON_A_RESPONSE",
                "B_FINAL_REVIEW",
            ):
                to_status = "PENDING_C_REVIEW"
                flash(
                    "Requires Dept C Review is checked — routing to Department C review.",
                    "info",
                )

            if (not req.requires_c_review) and to_status == "PENDING_C_REVIEW":
                to_status = "B_IN_PROGRESS"
                flash(
                    "Requires Dept C Review is not checked — keeping request out of Department C review.",
                    "info",
                )

        if not is_transition_valid_for_request(req, dept, req.status, to_status):
            flash("That transition isn't allowed from the current status.", "danger")
            return redirect(url_for("requests.request_detail", request_id=req.id))

        loop_warning = _detect_recent_transition_loop(req.id, req.status, to_status)
        if loop_warning:
            flash(loop_warning, "warning")
            return redirect(url_for("requests.request_detail", request_id=req.id))

        from_status = req.status

        approval_state = _approval_cycle_state(req.id, from_status, user=current_user)
        if (
            _approval_transition_requires_completion(from_status, to_status)
            and approval_state["has_configured_stages"]
            and not approval_state["ready"]
        ):
            flash(
                "Complete every configured approval stage before moving this request forward.",
                "warning",
            )
            return redirect(url_for("requests.request_detail", request_id=req.id))

        # Determine whether we should create a submission record. Create one when
        # this is a handoff (cross-department transfer) OR when the actor provided
        # a summary/details or attachments for this status update.
        handoff = handoff_for_transition(req.status, to_status)
        if selected_route and selected_route.get("to_department"):
            handoff = (
                selected_route.get("from_department") or req.owner_department,
                selected_route.get("to_department") or resolved_target_owner,
            )
        # If no explicit handoff rule exists but the owner department implied by the
        # target status differs from the current owner, treat this as a transfer
        # handoff (e.g., selecting a status that names a different department).
        if not handoff:
            target_owner = resolved_target_owner
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
            target_owner = resolved_target_owner
            if target_owner and target_owner != req.owner_department:
                from_dept = req.owner_department
                to_dept = target_owner
                create_submission = True
            else:
                # If user supplied summary/details or files, create a submission record
                has_summary = bool((form.submission_summary.data or "").strip())
                has_details = bool((form.submission_details.data or "").strip())
                has_files = bool(
                    form.files.data and any(f and f.filename for f in form.files.data)
                )
                if has_summary or has_details or has_files:
                    from_dept = req.owner_department
                    to_dept = resolved_target_owner or req.owner_department
                    create_submission = True

        if create_submission:
            # Require submission content only when the handoff crosses departments
            require_submission = from_dept != to_dept

            # Allow Dept A to close without providing a submission packet.
            if require_submission:
                if not (dept == "A" and to_status == "CLOSED"):
                    if not form.submission_summary.data:
                        flash(
                            "Submission Summary is required when transferring a request to another department.",
                            "danger",
                        )
                        return redirect(
                            url_for("requests.request_detail", request_id=req.id)
                        )

            try:
                validated = _validate_files(form.files.data)
            except ValueError as e:
                flash(str(e), "danger")
                return redirect(url_for("requests.request_detail", request_id=req.id))

            # SPECIAL RULE: If this request is currently owned by Department A and
            # is being sent back to Department B, require at least one image
            # attachment (screenshot) as part of the submission.
            try:
                if from_dept == "A" and to_dept == "B":
                    if not validated or len(validated) == 0:
                        flash(
                            "A screenshot (PNG/JPEG/WebP) is required when returning this request to Department B.",
                            "danger",
                        )
                        return redirect(
                            url_for("requests.request_detail", request_id=req.id)
                        )
            except Exception:
                flash(
                    "Submission validation failed; please attach a screenshot when sending back to Department B.",
                    "danger",
                )
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

            for f, size in validated:
                orig = secure_filename(f.filename)
                stored = f"{uuid.uuid4().hex}_{orig}"
                save_path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
                f.save(save_path)
                db.session.add(
                    Attachment(
                        submission_id=sub.id,
                        uploaded_by_user_id=current_user.id,
                        original_filename=orig,
                        stored_filename=stored,
                        content_type=f.mimetype,
                        size_bytes=size,
                    )
                )

            _log(
                req,
                "submission_created",
                note=f"Submission packet created ({from_dept}→{to_dept}).",
            )

            if handoff:
                req.status = to_status
                req.owner_department = resolved_target_owner

            if handoff:
                recipients = [
                    u for u in _users_in_dept(to_dept) if u.id != current_user.id
                ]
                notify_users(
                    recipients,
                    title=f"New handoff: {from_dept} → {to_dept} (Request #{req.id})",
                    body=sub.summary,
                    url=url_for("requests.request_detail", request_id=req.id),
                    ntype="handoff",
                    request_id=req.id,
                )
                try:
                    from ..models import IntegrationConfig

                    configs = IntegrationConfig.query.filter_by(
                        department=to_dept,
                        enabled=True,
                    ).all()
                    bundle_payload = build_handoff_bundle_payload(req, sub)
                    tc = TicketingClient()
                    for cfg in configs:
                        try:
                            cfg_data = json.loads(cfg.config) if cfg.config else {}
                        except Exception:
                            cfg_data = {}
                        bundle_options = cfg_data.get("handoff_bundle") or {}
                        if not bundle_options.get("enabled"):
                            continue

                        payload = dict(bundle_payload)
                        if not bundle_options.get("include_submission", True):
                            payload.pop("submission", None)
                        if not bundle_options.get("include_attachments", True):
                            payload["attachments"] = []

                        if cfg.kind == "ticketing" and bundle_options.get(
                            "create_ticket", True
                        ):
                            tc.create_ticket(
                                f"Handoff bundle for Request #{req.id}",
                                json.dumps(payload, default=str, indent=2),
                                metadata={
                                    "request_id": req.id,
                                    "dept": to_dept,
                                    **cfg_data,
                                },
                            )
                        elif cfg.kind == "webhook":
                            target_url = cfg_data.get("url") or (
                                cfg_data.get("endpoints") or {}
                            ).get("url")
                            if not target_url:
                                continue
                            requests = __import__("requests")
                            headers = {"Content-Type": "application/json"}
                            if cfg_data.get("token"):
                                headers["Authorization"] = (
                                    f"Bearer {cfg_data.get('token')}"
                                )
                            payload["event"] = (
                                bundle_options.get("event_name") or "handoff_bundle"
                            )
                            requests.post(
                                target_url,
                                json=payload,
                                headers=headers,
                                timeout=5,
                            )
                except Exception:
                    current_app.logger.exception(
                        "Failed to emit handoff bundle integration payload"
                    )

        req.status = to_status
        req.owner_department = resolved_target_owner
        if from_status != to_status:
            _create_approval_cycle_for_status(req, to_status)
        _log(
            req,
            "status_change",
            note=f"Status changed by Dept {dept}.",
            from_status=from_status,
            to_status=to_status,
        )

        try:
            metrics_module.request_transitions_total.labels(
                from_status=from_status or "", to_status=to_status or "", dept=dept
            ).inc()
        except Exception:
            current_app.logger.exception("Failed to record transition metric")

        try:
            from datetime import datetime

            if to_status == "CLOSED" and getattr(req, "due_at", None):
                now = datetime.utcnow()
                if req.due_at and now <= req.due_at:
                    try:
                        metrics_module.requests_closed_before_due_total.labels(
                            dept=req.owner_department
                        ).inc()
                    except Exception:
                        current_app.logger.exception(
                            "Failed to record closed-before-due metric"
                        )
        except Exception:
            current_app.logger.exception("Failed to evaluate closed-before-due metric")

        if dept == "B" and to_status == "SENT_TO_A":
            try:
                assigned_id = (
                    db.session.query(ReqModel.assigned_to_user_id)
                    .filter(ReqModel.id == request_id)
                    .scalar()
                )
            except Exception:
                assigned_id = None

            if assigned_id:
                previous = db.session.get(User, assigned_id)
                prev_label = (
                    (previous.name or previous.email) if previous else "Unassigned"
                )

                try:
                    db.session.query(ReqModel).filter(ReqModel.id == request_id).update(
                        {"assigned_to_user_id": None}, synchronize_session=False
                    )
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass

                try:
                    a = AuditLog(
                        request_id=request_id,
                        actor_type="user",
                        actor_user_id=getattr(current_user, "id", None),
                        actor_label=getattr(current_user, "email", None),
                        action_type="assignment_changed",
                        note=f"Assignment cleared as request sent to Dept A: {prev_label}",
                    )
                    db.session.add(a)
                except Exception:
                    try:
                        current_app.logger.exception("Failed to write audit log")
                    except Exception:
                        pass

                try:
                    if previous and getattr(previous, "is_active", True):
                        notify_users(
                            [previous],
                            title=f"Assignment cleared on Request #{request_id}",
                            body="Your assignment was cleared because the request was sent to Department A.",
                            url=url_for(
                                "requests.request_detail", request_id=request_id
                            ),
                            ntype="assignment_cleared",
                            request_id=request_id,
                        )
                    try:
                        metrics_module.assignment_changes_total.labels(
                            dept="B", action="cleared"
                        ).inc()
                    except Exception:
                        current_app.logger.exception(
                            "Failed to record assignment cleared metric"
                        )
                except Exception:
                    current_app.logger.exception(
                        "Failed to notify previous assignee about cleared assignment"
                    )

        owner_recipients = [
            u for u in _users_in_dept(req.owner_department) if u.id != current_user.id
        ]
        # always notify the assigned user as well, unless they're the one making the change
        if req.assigned_to_user and req.assigned_to_user.id != current_user.id:
            if req.assigned_to_user not in owner_recipients:
                owner_recipients.append(req.assigned_to_user)
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
            send_notification = True
            try:
                from ..models import StatusOption

                opt = StatusOption.query.filter_by(code=to_status).first()
                if opt:
                    if not opt.notify_enabled:
                        send_notification = False
                    elif opt.notify_on_transfer_only:
                        prev_owner = (
                            owner_for_status(from_status) if from_status else None
                        )
                        new_owner = owner_for_status(to_status)
                        if prev_owner == new_owner:
                            send_notification = False
            except Exception:
                opt = None

            if send_notification:
                try:
                    if opt and bool(getattr(opt, "notify_to_originator_only", False)):
                        originator = None
                        if req.created_by_user_id:
                            originator = db.session.get(User, req.created_by_user_id)
                        if (
                            originator
                            and getattr(originator, "is_active", True)
                            and originator.id != current_user.id
                        ):
                            owner_recipients = [originator]
                        else:
                            owner_recipients = []
                        # the assigned user should still get updates even if
                        # the admin opted to notify only the originator
                        if (
                            req.assigned_to_user
                            and req.assigned_to_user.id != current_user.id
                        ):
                            if req.assigned_to_user not in owner_recipients:
                                owner_recipients.append(req.assigned_to_user)
                except Exception:
                    current_app.logger.exception(
                        "Failed to apply originator-only notify rule"
                    )

                allow_email = True
                if opt:
                    allow_email = bool(getattr(opt, "email_enabled", False))
                notify_users(
                    owner_recipients,
                    title=f"Request #{req.id} moved to {req.status}",
                    body=body_text,
                    url=url_for("requests.request_detail", request_id=req.id),
                    ntype="status_change",
                    request_id=req.id,
                    allow_email=allow_email,
                )
                try:
                    from ..models import IntegrationConfig

                    configs = IntegrationConfig.query.filter_by(
                        department=req.owner_department, enabled=True
                    ).all()
                    tc = TicketingClient()
                    for cfg in configs:
                        try:
                            cfg_data = json.loads(cfg.config) if cfg.config else {}
                        except Exception:
                            cfg_data = {}
                        if cfg.kind == "ticketing":
                            summary = f"Request #{req.id} moved to {req.status}"
                            desc = body_text
                            try:
                                tc.create_ticket(
                                    summary,
                                    desc,
                                    metadata={
                                        "request_id": req.id,
                                        "dept": req.owner_department,
                                        **cfg_data,
                                    },
                                )
                            except Exception:
                                current_app.logger.exception(
                                    "Failed to create ticket via TicketingClient"
                                )
                        elif cfg.kind == "webhook" and cfg_data.get("url"):
                            try:
                                requests = __import__("requests")
                                headers = {"Content-Type": "application/json"}
                                if cfg_data.get("token"):
                                    headers["Authorization"] = (
                                        f"Bearer {cfg_data.get('token')}"
                                    )
                                payload = {
                                    "event": "status_change",
                                    "request_id": req.id,
                                    "from_status": from_status,
                                    "to_status": to_status,
                                    "department": req.owner_department,
                                }
                                requests.post(
                                    cfg_data.get("url"),
                                    json=payload,
                                    headers=headers,
                                    timeout=5,
                                )
                            except Exception:
                                current_app.logger.exception(
                                    "Failed to POST webhook for integration"
                                )
                except Exception:
                    current_app.logger.exception(
                        "Failed to process integration configs"
                    )

        if req.created_by_user_id and req.created_by_user_id != current_user.id:
            creator = db.session.get(User, req.created_by_user_id)
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
        try:
            emit_webhook_event(
                "request.status_changed",
                {
                    "request": serialize_request(req),
                    "from_status": from_status,
                    "to_status": to_status,
                },
            )
        except Exception:
            current_app.logger.exception("Failed to emit status-change event")
        try:
            record_process_metric_event(
                req,
                event_type="status_changed",
                actor_user=current_user,
                actor_department=getattr(current_user, "department", None),
                from_status=from_status,
                to_status=to_status,
                metadata={"handoff_department": req.owner_department},
            )
        except Exception:
            current_app.logger.exception("Failed to record status-change metric event")
        flash(f"Moved to {to_status}.", "success")
        try:
            if current_app.testing:
                return ("OK", 200)
        except Exception:
            pass
        return redirect(url_for("requests.request_detail", request_id=req.id))

    # Execute transition with a retry on DetachedInstanceError (re-querying once)
    try:
        return _run_transition(req)
    except DetachedInstanceError:
        try:
            req = (
                db.session.query(ReqModel)
                .options(
                    selectinload(ReqModel.assigned_to_user),
                    selectinload(ReqModel.artifacts),
                )
                .filter(ReqModel.id == request_id)
                .one()
            )
        except Exception:
            req = get_or_404(ReqModel, request_id)
        # Retry once
        return _run_transition(req)


@requests_bp.route("/requests/<int:request_id>/assign", methods=["POST"])
@login_required
def assign_request(request_id: int):
    req = get_or_404(ReqModel, request_id)
    if not can_view_request(req):
        abort(403)
    if current_user.department not in ("A", "B", "C"):
        abort(403)
    # Dept B may assign requests they own. Dept C may assign requests that
    # are awaiting C review so C users can claim/assign them locally. Dept A
    # may assign requests it owns when the request is currently owned by A.
    if not (
        (current_user.department == "B" and req.owner_department == "B")
        or (
            current_user.department == "C"
            and req.status == "PENDING_C_REVIEW"
            and req.requires_c_review
        )
        or (current_user.department == "A" and req.owner_department == "A")
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

    # Enforce: assignees may only have one active assigned request at a time.
    if new_assignee:
        existing = (
            ReqModel.query.filter(
                ReqModel.assigned_to_user_id == new_assignee.id,
                ReqModel.id != req.id,
                ReqModel.status != "CLOSED",
                ReqModel.is_denied == False,
            )
            .order_by(ReqModel.created_at.asc())
            .first()
        )
        if existing:
            flash(
                f"{new_assignee.name or new_assignee.email} is already assigned to Request #{existing.id}. Clear that assignment first.",
                "warning",
            )
            return redirect(url_for("requests.request_detail", request_id=req.id))

    # Re-query previous assignee from the session to avoid DetachedInstanceError
    previous = (
        db.session.get(User, req.assigned_to_user_id)
        if req.assigned_to_user_id
        else None
    )
    if (previous.id if previous else None) == (
        new_assignee.id if new_assignee else None
    ):
        flash("Assignment unchanged.", "info")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    req.assigned_to_user = new_assignee

    prev_label = (previous.name or previous.email) if previous else "Unassigned"
    new_label = (
        (new_assignee.name or new_assignee.email) if new_assignee else "Unassigned"
    )
    _log(
        req,
        "assignment_changed",
        note=f"Assignment changed: {prev_label} → {new_label}",
    )

    notif_targets = []
    if new_assignee and new_assignee.id != current_user.id:
        notif_targets.append(new_assignee)
    if req.created_by_user_id and req.created_by_user_id != current_user.id:
        creator = db.session.get(User, req.created_by_user_id)
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
        metrics_module.assignment_changes_total.labels(
            dept=current_user.department,
            action="assigned" if new_assignee else "cleared",
        ).inc()
        metrics_module.update_owner_gauge(db.session, ReqModel)
        record_process_metric_event(
            req,
            event_type="assignment_changed",
            actor_user=current_user,
            actor_department=getattr(current_user, "department", None),
            to_status=req.status,
            metadata={
                "assignment_action": "assigned" if new_assignee else "cleared",
                "assigned_to_user_id": getattr(new_assignee, "id", None),
            },
        )
    except Exception:
        current_app.logger.exception("Failed to update metrics on assignment change")

    return redirect(url_for("requests.request_detail", request_id=req.id))


@requests_bp.route("/requests/<int:request_id>/toggle_c_review", methods=["POST"])
@login_required
def toggle_c_review(request_id: int):
    req = get_or_404(ReqModel, request_id)

    if current_user.department != "B":
        abort(403)
    if not can_view_request(req):
        abort(403)

    rv = _require_assigned_user(req)
    if rv:
        return rv

    if req.status not in ("NEW_FROM_A", "B_IN_PROGRESS"):
        flash(
            "C review can only be toggled while the request is NEW_FROM_A or B_IN_PROGRESS.",
            "danger",
        )
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
    att = get_or_404(Attachment, attachment_id)
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


@requests_bp.route("/requests/<int:request_id>/upload_screenshots", methods=["POST"])
@login_required
def upload_screenshots(request_id: int):
    req = get_or_404(ReqModel, request_id)
    if not can_view_request(req):
        abort(403)

    # Require assignment for mutating actions
    rv = _require_assigned_user(req)
    if rv:
        return rv

    # Collect files from the form
    files = request.files.getlist("screenshots")
    try:
        validated = _validate_files(files)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    if not validated:
        flash("No valid screenshot files provided.", "warning")
        return redirect(url_for("requests.request_detail", request_id=req.id))

    # Create a lightweight submission to hold the screenshots
    sub = Submission(
        request_id=req.id,
        from_department=current_user.department,
        to_department=req.owner_department,
        from_status=req.status,
        to_status=req.status,
        summary="Screenshots",
        details="Uploaded screenshots",
        is_public_to_submitter=False,
        created_by_user_id=current_user.id,
    )
    db.session.add(sub)
    db.session.flush()

    for f, size in validated:
        orig = secure_filename(f.filename)
        stored = f"{uuid.uuid4().hex}_{orig}"
        save_path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
        f.save(save_path)
        db.session.add(
            Attachment(
                submission_id=sub.id,
                uploaded_by_user_id=current_user.id,
                original_filename=orig,
                stored_filename=stored,
                content_type=f.mimetype,
                size_bytes=size,
            )
        )

    _log(req, "submission_created", note="Screenshots uploaded")
    db.session.commit()
    flash("Screenshots uploaded.", "success")
    return redirect(url_for("requests.request_detail", request_id=req.id))
