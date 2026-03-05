from datetime import datetime, timedelta
from flask import url_for
from ..extensions import db
from ..models import Request as ReqModel, User, Notification

def users_in_dept(dept: str):
    return User.query.filter_by(department=dept, is_active=True).all()

def send_due_soon_notifications(app, hours=24):
    now = datetime.utcnow()
    soon = now + timedelta(hours=hours)

    # not closed + has due date within window
    reqs = (ReqModel.query
            .filter(ReqModel.due_at != None)
            .filter(ReqModel.due_at <= soon)
            .filter(ReqModel.status != "CLOSED")
            .all())

    for req in reqs:
        link = url_for("requests.request_detail", request_id=req.id, _external=False)

        targets = users_in_dept(req.owner_department)
        if req.created_by_user_id:
            creator = User.query.get(req.created_by_user_id)
            if creator and creator.is_active:
                targets.append(creator)

        # dedupe per user per req per window
        dedupe = f"due_{hours}h:req_{req.id}"

        for u in {t.id: t for t in targets}.values():
            exists = Notification.query.filter_by(user_id=u.id, dedupe_key=dedupe).first()
            if exists:
                continue

            db.session.add(Notification(
                user_id=u.id,
                request_id=req.id,
                type="due_soon",
                title=f"Due soon: Request #{req.id}",
                body=f"Due at {req.due_at}",
                url=link,
                dedupe_key=dedupe,
            ))

    db.session.commit()