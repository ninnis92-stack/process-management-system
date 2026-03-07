from app import create_app
from app.extensions import db
from app.models import (
    User,
    Request as ReqModel,
    FormTemplate,
    FormField,
    DepartmentFormAssignment,
    StatusBucket,
    BucketStatus,
)
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

app = create_app()
app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SERVER_NAME="localhost")

with app.app_context():
    db.drop_all()
    db.create_all()
    u = User(
        email="admin@example.com",
        password_hash=generate_password_hash("secret", method="pbkdf2:sha256"),
        department="B",
        is_active=True,
        is_admin=True,
    )
    db.session.add(u)
    db.session.commit()
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
    # import buckets
    layout = [
        ("New", ["NEW_FROM_A"]),
        ("In Progress", ["B_IN_PROGRESS", "PENDING_C_REVIEW", "B_FINAL_REVIEW"]),
        ("Needs Input", ["WAITING_ON_A_RESPONSE", "C_NEEDS_CHANGES"]),
        ("Pending Approval", ["EXEC_APPROVAL", "C_APPROVED", "SENT_TO_A"]),
        ("Completed", ["CLOSED"]),
        ("Archived", []),
    ]
    for idx, (name, statuses) in enumerate(layout):
        exists = StatusBucket.query.filter_by(name=name, department_name="B").first()
        if exists:
            for s in exists.statuses.all():
                db.session.delete(s)
            for sidx, code in enumerate(statuses):
                db.session.add(
                    BucketStatus(bucket_id=exists.id, status_code=code, order=sidx)
                )
            db.session.commit()
            continue
        b = StatusBucket(name=name, department_name="B", order=idx, active=True)
        db.session.add(b)
        db.session.commit()
        for sidx, code in enumerate(statuses):
            db.session.add(BucketStatus(bucket_id=b.id, status_code=code, order=sidx))
        db.session.commit()

    in_progress = StatusBucket.query.filter_by(
        name="In Progress", department_name="B"
    ).first()
    print("Bucket id", in_progress.id)
    client = app.test_client()
    client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "secret"},
        follow_redirects=True,
    )
    rv = client.get(f"/dashboard?bucket_id={in_progress.id}")
    html = rv.data.decode()
    print("HTML length", len(html))
    # print snippet around titles
    for title in ["Progress Item", "Needs Input Item"]:
        idx = html.find(title)
        print(title, "found at", idx)
        if idx != -1:
            print(html[max(0, idx - 1000) : idx + 1000])
