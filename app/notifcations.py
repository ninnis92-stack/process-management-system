from .extensions import db
from .models import Noti***REMOVED***cation, User

def users_in_department(dept: str):
    return User.query.***REMOVED***lter_by(department=dept, is_active=True).all()

def notify_users(users, title, body=None, url=None, ntype="generic", request_id=None):
    for u in users:
        db.session.add(
            Noti***REMOVED***cation(
                user_id=u.id,
                request_id=request_id,
                type=ntype,
                title=title,
                body=body,
                url=url,
            )
        )
    # ✅ do NOT commit here; commit happens in the route after all writes