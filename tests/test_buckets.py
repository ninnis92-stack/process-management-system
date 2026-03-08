import pytest
from app.extensions import db
from app.models import User, Request as ReqModel, StatusBucket, BucketStatus
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta


def login_admin(client, email="admin@example.com", password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_bucket_import_and_filtering(app, client):
    # Setup admin user and some requests
    with app.app_context():
        # create admin user
        u = User(
            email="admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(u)
        db.session.commit()

        # create a couple of requests
        r1 = ReqModel(
            title="Progress Item",
            request_type="both",
            pricebook_status="unknown",
            description="x",
            priority="medium",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=2)),
        )
        r2 = ReqModel(
            title="Needs Input Item",
            request_type="both",
            pricebook_status="unknown",
            description="y",
            priority="low",
            status="WAITING_ON_A_RESPONSE",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=5)),
        )
        db.session.add_all([r1, r2])
        db.session.commit()

    # login as admin
    rv = login_admin(client)
    assert rv.status_code == 200

    # import default buckets
    rv = client.post("/admin/buckets/import_default", follow_redirects=True)
    assert b"Imported recommended buckets" in rv.data

    # find the 'In Progress' bucket id
    with app.app_context():
        in_progress = StatusBucket.query.filter_by(
            name="In Progress", department_name="B"
        ).first()
        assert in_progress is not None
        # ensure it maps to B_IN_PROGRESS
        codes = [s.status_code for s in in_progress.statuses.all()]
        assert "B_IN_PROGRESS" in codes

    # request dashboard filtered by bucket_id
    rv = client.get(f"/dashboard?bucket_id={in_progress.id}")
    assert rv.status_code == 200
    # debug snapshot to understand layout changes (full html)
    debug_html = rv.data.decode(errors='ignore')
    print('dashboard html length', len(debug_html))
    print(debug_html)
    # should include the Progress Item
    assert b"Progress Item" in rv.data
    # should not include the Needs Input Item in this bucket
    assert b"Needs Input Item" not in rv.data


def test_bucket_filtering_other_departments(app, client):
    # verify that admin-defined buckets work for Dept A and Dept C as well
    with app.app_context():
        # create admin user
        u = User(
            email="admin2@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=True,
        )
        db.session.add(u)
        db.session.commit()

        # dept A bucket
        a_bucket = StatusBucket(name="A Bucket", department_name="A", order=0, active=True)
        db.session.add(a_bucket)
        db.session.flush()
        db.session.add(BucketStatus(bucket_id=a_bucket.id, status_code="A_SPECIAL", order=0))

        # dept C bucket
        c_bucket = StatusBucket(name="C Bucket", department_name="C", order=0, active=True)
        db.session.add(c_bucket)
        db.session.flush()
        db.session.add(BucketStatus(bucket_id=c_bucket.id, status_code="PENDING_C_REVIEW", order=0))

        # requests for A
        rA1 = ReqModel(
            title="A Item",
            request_type="both",
            pricebook_status="unknown",
            description="a",
            priority="medium",
            status="A_SPECIAL",
            owner_department="A",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=2)),
        )
        rA2 = ReqModel(
            title="A Other",
            request_type="both",
            pricebook_status="unknown",
            description="b",
            priority="low",
            status="OTHER",
            owner_department="A",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=5)),
        )
        # request for C (status filter only)
        rC1 = ReqModel(
            title="C Item",
            request_type="both",
            pricebook_status="unknown",
            description="c",
            priority="low",
            status="PENDING_C_REVIEW",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        rC2 = ReqModel(
            title="C Other",
            request_type="both",
            pricebook_status="unknown",
            description="d",
            priority="low",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        db.session.add_all([rA1, rA2, rC1, rC2])
        db.session.commit()

    # login as admin
    rv = login_admin(client, email="admin2@example.com")
    assert rv.status_code == 200

    # Dept A view
    rv = client.get(f"/dashboard?as_dept=A")
    assert b"A Bucket" in rv.data
    rv = client.get(f"/dashboard?as_dept=A&bucket_id={a_bucket.id}")
    assert b"A Item" in rv.data
    assert b"A Other" not in rv.data

    # Dept C view
    rv = client.get(f"/dashboard?as_dept=C")
    assert b"C Bucket" in rv.data
    rv = client.get(f"/dashboard?as_dept=C&bucket_id={c_bucket.id}")
    assert b"C Item" in rv.data
    assert b"C Other" not in rv.data
