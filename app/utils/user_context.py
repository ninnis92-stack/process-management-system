import hashlib

from ..extensions import db


def gravatar_url(email, size=34, default="mp"):
    if not email:
        return f"https://www.gravatar.com/avatar/?d={default}&s={size}"
    try:
        normalized = email.strip().lower().encode("utf-8")
        digest = hashlib.md5(normalized).hexdigest()
        return f"https://www.gravatar.com/avatar/{digest}?d={default}&s={size}"
    except Exception:
        return f"https://www.gravatar.com/avatar/?d={default}&s={size}"


def avatar_url_for(user, size=34):
    if not user:
        return gravatar_url(None, size)
    picture = getattr(user, "sso_picture", None) or getattr(user, "picture", None)
    if picture:
        return picture
    return gravatar_url(getattr(user, "email", None), size)


def get_user_departments(user):
    """Return ordered department codes the user may act as."""
    if not user:
        return []
    try:
        from ..models import Department, UserDepartment

        depts = []
        primary = (
            getattr(user, "_stored_primary_department", None)
            or getattr(user, "department", None)
            or ""
        ).strip().upper()
        if primary:
            depts.append(primary)

        assignments = []
        if getattr(user, "id", None):
            assignments = (
                UserDepartment.query.filter_by(user_id=user.id)
                .order_by(UserDepartment.id.asc(), UserDepartment.department.asc())
                .all()
            )
        else:
            assignments = sorted(
                getattr(user, "departments", []) or [],
                key=lambda assignment: (
                    getattr(assignment, "id", 0) or 0,
                    (getattr(assignment, "department", None) or "").strip().upper(),
                ),
            )
        for assignment in assignments:
            if getattr(assignment, "is_active_assignment", True) is False:
                continue
            dept = (getattr(assignment, "department", None) or "").strip().upper()
            if dept and dept not in depts:
                depts.append(dept)

        if getattr(user, "is_admin", False):
            rows = (
                Department.query.filter_by(is_active=True)
                .order_by(Department.order.asc(), Department.code.asc())
                .all()
            )
            admin_depts = [
                (row.code or "").strip().upper()
                for row in rows
                if (row.code or "").strip()
            ]
            return admin_depts or depts

        return depts
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        dept = (getattr(user, "department", None) or "").strip().upper()
        return [dept] if dept else []


def user_has_multiple_departments(user):
    return len(get_user_departments(user)) > 1


def user_can_access_department(user, dept):
    normalized = (dept or "").strip().upper()
    if not normalized or not user:
        return False
    try:
        if getattr(user, "is_admin", False):
            return True
        return normalized in set(get_user_departments(user))
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def can_view_metrics_for_user(user):
    try:
        if not user or not getattr(user, "id", None):
            return False
        if getattr(user, "is_admin", False):
            return True

        from ..models import DepartmentEditor

        roles = DepartmentEditor.query.filter_by(user_id=user.id).all()
        return any(bool(getattr(role, "can_view_metrics", False)) for role in roles)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def is_external_theme_active(site_config=None):
    """Return True when imported branding should override user vibe controls."""
    try:
        from ..models import SiteConfig

        try:
            from ..models import AppTheme
        except Exception:
            AppTheme = None

        if AppTheme is not None:
            theme = AppTheme.query.filter_by(active=True).first()
            if theme and (
                getattr(theme, "logo_filename", None) or getattr(theme, "css", None)
            ):
                return True

        cfg = site_config or SiteConfig.get()
        if getattr(cfg, "logo_filename", None):
            return True
        preset = (getattr(cfg, "theme_preset", None) or "").strip().lower()
        return bool(preset and preset != "default")
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return False
