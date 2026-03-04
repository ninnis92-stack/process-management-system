from flask import Blueprint, jsonify, redirect, url_for, request
from flask_login import login_required, current_user
from ..extensions import db
from ..models import Noti***REMOVED***cation

noti***REMOVED***cations_bp = Blueprint("noti***REMOVED***cations", __name__, url_pre***REMOVED***x="/noti***REMOVED***cations")

@noti***REMOVED***cations_bp.get("/unread_count")
@login_required
def unread_count():
    count = Noti***REMOVED***cation.query.***REMOVED***lter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({"count": count})

@noti***REMOVED***cations_bp.get("/latest")
@login_required
def latest():
    items = Noti***REMOVED***cation.query.***REMOVED***lter_by(user_id=current_user.id).order_by(Noti***REMOVED***cation.created_at.desc()).limit(10).all()
    return jsonify([{
        "id": n.id,
        "title": n.title,
        "body": n.body,
        "url": n.url,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat(),
    } for n in items])

@noti***REMOVED***cations_bp.post("/<int:notif_id>/read")
@login_required
def mark_read(notif_id: int):
    n = Noti***REMOVED***cation.query.***REMOVED***lter_by(id=notif_id, user_id=current_user.id).***REMOVED***rst_or_404()
    n.is_read = True
    db.session.commit()
    return jsonify({"ok": True})