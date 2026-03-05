#!/usr/bin/env python3
from datetime import datetime, timedelta
from app import create_app
from app.extensions import db
from app.models import Request, User


def create_guest_request(idx):
    title = f"Guest Request {idx}"
    r = Request(
        title=title,
        request_type="both",
        pricebook_status="unknown",
        description=f"Guest-submitted request #{idx}",
        priority="medium",
        submitter_type="guest",
        guest_email=f"guest{idx}@example.com",
        guest_name=f"Guest {idx}",
        due_at=datetime.utcnow() + timedelta(days=7),
    )
    r.ensure_guest_token(days_valid=14)
    db.session.add(r)
    return r


def create_dept_a_request(idx, created_by_user):
    title = f"Dept A Request {idx}"
    r = Request(
        title=title,
        request_type="part_number",
        pricebook_status="unknown",
        description=f"Department A created request #{idx}",
        priority="high" if idx % 2 == 0 else "medium",
        submitter_type="user",
        created_by_user=created_by_user,
        owner_department="B",  # target owner is Dept B for testing
        due_at=datetime.utcnow() + timedelta(days=3 + idx),
    )
    db.session.add(r)
    return r


def main():
    app = create_app()
    with app.app_context():
        # ***REMOVED***nd or create a Dept A user
        a_user = User.query.***REMOVED***lter_by(email="a@example.com").***REMOVED***rst()
        if not a_user:
            a_user = User(email="a@example.com", name="Dept A User", password_hash="x", department="A", is_active=True)
            db.session.add(a_user)
            db.session.commit()

        created = []
        for i in range(1, 4):
            r = create_guest_request(i)
            created.append(r)

        for i in range(1, 4):
            r = create_dept_a_request(i, a_user)
            created.append(r)

        db.session.commit()

        print("Created requests:")
        for r in created:
            print(f"- id={r.id} title={r.title} submitter={r.submitter_type} owner={r.owner_department} guest_token={getattr(r, 'guest_access_token', None)} status={r.status}")

        # counts for Dept B relevant buckets
        total = Request.query.count()
        new_from_a = Request.query.***REMOVED***lter_by(status='NEW_FROM_A').count()
        in_progress = Request.query.***REMOVED***lter_by(status='B_IN_PROGRESS').count()
        print(f"Totals: all={total} NEW_FROM_A={new_from_a} B_IN_PROGRESS={in_progress}")


if __name__ == '__main__':
    main()
