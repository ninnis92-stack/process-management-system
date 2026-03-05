#!/usr/bin/env python3
from datetime import datetime
from app import create_app
from app.extensions import db
from app.models import Request, Submission, AuditLog, Comment, User


def main():
    app = create_app()
    with app.app_context():
        b_user = User.query.***REMOVED***lter_by(email='b@example.com').***REMOVED***rst()
        if not b_user:
            print('Dept B user not found; run seed.py ***REMOVED***rst')
            return

        reqs = Request.query.order_by(Request.id.asc()).limit(6).all()
        if not reqs:
            print('No requests found; run create_smoke_requests.py ***REMOVED***rst')
            return

        # Req 1 -> B_IN_PROGRESS, assigned to B user
        r1 = reqs[0]
        old = r1.status
        r1.status = 'B_IN_PROGRESS'
        r1.owner_department = 'B'
        r1.assigned_to_user = b_user
        db.session.add(AuditLog(request_id=r1.id, actor_type='user', actor_user_id=b_user.id,
                                action_type='status_change', from_status=old, to_status=r1.status,
                                note='Auto-populated for UI testing'))

        # Req 2 -> PENDING_C_REVIEW (handoff B->C) with submission
        r2 = reqs[1]
        old = r2.status
        r2.status = 'PENDING_C_REVIEW'
        r2.owner_department = 'C'
        sub = Submission(request_id=r2.id, from_department='B', to_department='C',
                         from_status=old, to_status=r2.status,
                         summary='Please review materials', details='Auto-generated handoff for Dept C review',
                         is_public_to_submitter=False, created_by_user_id=b_user.id)
        db.session.add(sub)
        db.session.add(AuditLog(request_id=r2.id, actor_type='user', actor_user_id=b_user.id,
                                action_type='submission_created', note='Auto handoff B->C'))
        db.session.add(AuditLog(request_id=r2.id, actor_type='user', actor_user_id=b_user.id,
                                action_type='status_change', from_status=old, to_status=r2.status,
                                note='Auto-populated for UI testing'))

        # Req 3 -> B_FINAL_REVIEW, assigned
        r3 = reqs[2]
        old = r3.status
        r3.status = 'B_FINAL_REVIEW'
        r3.owner_department = 'B'
        r3.assigned_to_user = b_user
        db.session.add(AuditLog(request_id=r3.id, actor_type='user', actor_user_id=b_user.id,
                                action_type='status_change', from_status=old, to_status=r3.status,
                                note='Auto-populated for UI testing'))

        # Req 4 -> WAITING_ON_A_RESPONSE
        r4 = reqs[3]
        old = r4.status
        r4.status = 'WAITING_ON_A_RESPONSE'
        r4.owner_department = 'B'
        db.session.add(AuditLog(request_id=r4.id, actor_type='user', actor_user_id=b_user.id,
                                action_type='status_change', from_status=old, to_status=r4.status,
                                note='Auto-populated for UI testing'))

        # Req 5 -> NEW_FROM_A (leave as is) but add a comment
        r5 = reqs[4]
        db.session.add(Comment(request_id=r5.id, author_type='user', author_user_id=b_user.id,
                               visibility_scope='dept_b_internal', body='Investigate this part number.'))

        # Req 6 -> CLOSED
        r6 = reqs[5]
        old = r6.status
        r6.status = 'CLOSED'
        r6.owner_department = 'B'
        db.session.add(AuditLog(request_id=r6.id, actor_type='user', actor_user_id=b_user.id,
                                action_type='status_change', from_status=old, to_status=r6.status,
                                note='Auto-populated for UI testing'))

        db.session.commit()

        print('Populated sample transitions:')
        for r in reqs:
            print(f'id={r.id} status={r.status} owner={r.owner_department} assigned_to={getattr(r.assigned_to_user, "email", None)}')

if __name__ == '__main__':
    main()
