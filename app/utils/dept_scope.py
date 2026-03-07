from functools import wraps
from flask import current_app, abort
from flask_login import current_user
from ..extensions import db
from ..models import Request as ReqModel, Submission
from sqlalchemy import or_, select


def scope_requests_for_department(query, dept: str):
    """Return a query limited to requests owned by `dept` or explicitly
    sent to `dept` via a Submission."""
    if not dept:
        return query
    sent_sel = select(Submission.request_id).where(Submission.to_department == dept)
    return query.filter(
        or_(ReqModel.owner_department == dept, ReqModel.id.in_(sent_sel))
    )


def enforce_dept_view(func):
    """Decorator for view functions that accept `request_id` and should
    check department-scoped visibility using `can_view_request`.

    Usage: decorate endpoints that render or mutate a single Request to
    centralize the visibility check. Functions that already call
    `can_view_request` need not add this decorator.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Defer to the app-level permission helper if available.
        try:
            from ..requests_bp.permissions import can_view_request
        except Exception:
            can_view = None
        else:
            can_view = can_view_request

        # If we have a permission helper, call it after resolving the request.
        req = None
        rid = kwargs.get("request_id") or (args[0] if args else None)
        if rid is not None:
            try:
                req = db.session.get(ReqModel, int(rid))
            except Exception:
                req = None
        if req and can_view:
            if not can_view(req):
                abort(403)
        return func(*args, **kwargs)

    return wrapper
