from flask_login import current_user
from flask import current_app
from ..models import Request, Submission


def can_view_request(req: Request) -> bool:
    """Determine whether the currently logged-in user may view `req`.

    By default the historical permissive behavior is preserved. When the
    `ENFORCE_DEPT_ISOLATION` config flag is True this function tightens
    visibility so users only see requests owned by their department or
    explicitly handed off to them via a Submission. Admin users still
    retain full visibility.
    """
    if not current_user.is_authenticated:
        return False

    # Allow admins to view debug requests regardless of department
    if getattr(req, 'is_debug', False) and getattr(current_user, 'is_admin', False):
        return True

    # Admins always have full visibility
    if getattr(current_user, 'is_admin', False):
        return True

    enforce = current_app.config.get('ENFORCE_DEPT_ISOLATION', False)
    if not enforce:
        # Preserve existing permissive behavior for B/C users
        if current_user.department in ("B", "C"):
            return True
        # Dept A: allow if created by this user or if Dept A currently owns the request
        return req.created_by_user_id == current_user.id or req.owner_department == "A"

    # Strict isolation mode: only allow when owned by user's dept or explicitly sent to it
    dept = getattr(current_user, 'department', None)
    if not dept:
        return False

    if req.owner_department == dept:
        return True

    # Allow when a Submission explicitly sent the request to this department
    sent = Submission.query.filter_by(request_id=req.id, to_department=dept).first()
    if sent:
        return True

    # Special-case: Dept C may view when the request is currently awaiting C review
    if dept == 'C' and req.status == 'PENDING_C_REVIEW':
        return True

    # Otherwise deny
    return False

def visible_comment_scopes_for_user() -> set[str]:
    if not current_user.is_authenticated:
        return {"public"}
    dept = current_user.department
    if dept == "A":
        return {"public", "dept_a_internal"}
    if dept == "B":
        return {"public", "dept_b_internal"}
    if dept == "C":
        return {"public", "dept_c_internal"}
    return {"public"}

def allowed_comment_scopes_for_user() -> list[str]:
    if not current_user.is_authenticated:
        return ["public"]
    dept = current_user.department
    if dept == "A":
        return ["public", "dept_a_internal"]
    if dept == "B":
        return ["public", "dept_b_internal"]
    if dept == "C":
        return ["public", "dept_c_internal"]
    return ["public"]