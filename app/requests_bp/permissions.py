from flask_login import current_user
from ..models import Request

def can_view_request(req: Request) -> bool:
    if current_user.is_authenticated:
        # Allow admins to view debug requests regardless of department
        if getattr(req, 'is_debug', False) and getattr(current_user, 'is_admin', False):
            return True

        if current_user.department in ("B", "C"):
            return True
        # Dept A: allow if created by this user or if Dept A currently owns the request
        return req.created_by_user_id == current_user.id or req.owner_department == "A"
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