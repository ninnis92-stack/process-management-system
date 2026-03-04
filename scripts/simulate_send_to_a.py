from app import create_app
from app.extensions import db
from app.models import User, Request as ReqModel, Submission, Noti***REMOVED***cation
from app.requests_bp.workflow import owner_for_status
from app.requests_bp.routes import notify_users, users_in_department

app = create_app()

with app.app_context():
    # ***REMOVED***nd a Dept B user to act as the actor
    actor = User.query.***REMOVED***lter_by(department='B').***REMOVED***rst()
    if not actor:
        print('No Dept B user found')
        raise SystemExit(1)

    # Create a request currently in B_FINAL_REVIEW owned by B
    from datetime import datetime, timedelta

    req = ReqModel(
        title='Simulated handoff to A',
        request_type='part_number',
        pricebook_status='unknown',
        description='Simulated request to test noti***REMOVED***cations',
        priority='medium',
        requires_c_review=False,
        status='B_FINAL_REVIEW',
        owner_department='B',
        submitter_type='user',
        created_by_user_id=actor.id,
        due_at=datetime.utcnow() + timedelta(days=3),
    )
    db.session.add(req)
    db.session.flush()

    # Create a Submission for the handoff (B -> A)
    sub = Submission(
        request_id=req.id,
        from_department='B',
        to_department='A',
        from_status='B_FINAL_REVIEW',
        to_status='SENT_TO_A',
        summary='Automated handoff',
        details='Details for automated handoff',
        is_public_to_submitter=False,
        created_by_user_id=actor.id,
    )
    db.session.add(sub)

    # Notify recipients in Dept A (exclude actor if present)
    recipients = [u for u in users_in_department('A') if u.id != actor.id]
    notify_users(
        recipients,
        title=f"New handoff: B → A (Request #{req.id})",
        body=sub.summary,
        url=f"/requests/{req.id}",
        ntype='handoff',
        request_id=req.id,
    )

    # Update request status and owner
    req.status = 'SENT_TO_A'
    req.owner_department = owner_for_status(req.status)

    db.session.commit()

    print('Created request', req.id)
    print('Noti***REMOVED***cations for Dept A:')
    for n in Noti***REMOVED***cation.query.***REMOVED***lter(Noti***REMOVED***cation.user.has(department='A')).order_by(Noti***REMOVED***cation.created_at.desc()).limit(10):
        print(n.id, n.user.email, n.title, n.url, 'read' if n.is_read else 'unread')
