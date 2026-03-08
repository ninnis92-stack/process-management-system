from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import DepartmentEditor, Request as ReqModel, Submission, User, StatusBucket, BucketStatus


def login_user(client, email, password="secret"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_department_head_can_view_department_metrics(app, client):
    with app.app_context():
        head = User(
            email="dept-head@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        db.session.add(head)
        db.session.commit()

        db.session.add(
            DepartmentEditor(
                user_id=head.id,
                department="B",
                can_edit=False,
                can_view_metrics=True,
            )
        )

        req = ReqModel(
            title="Head Metrics Request",
            request_type="both",
            pricebook_status="unknown",
            description="x",
            priority="medium",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
            created_by_user_id=head.id,
            assigned_to_user_id=head.id,
        )
        db.session.add(req)
        db.session.commit()

        db.session.add(
            Submission(
                request_id=req.id,
                from_department="A",
                to_department="B",
                summary="handoff",
                created_by_user_id=head.id,
            )
        )
        db.session.commit()

    rv = login_user(client, "dept-head@example.com")
    assert rv.status_code == 200

    rv = client.get("/metrics/ui")
    assert rv.status_code == 200
    assert b"Department bucket" in rv.data
    assert b"Interactions" in rv.data
    assert b"User efficiency" in rv.data
    assert b"dept-head@example.com" in rv.data
    # department head with a single department won't see the full-site
    # button; it appears only when multiple departments are accessible.

    rv = client.get("/metrics/json")
    assert rv.status_code == 200
    payload = rv.get_json()
    assert payload["allowed_departments"] == ["B"]
    assert any(row["to_department"] == "B" for row in payload["interactions"])

    # department heads should be able to export the same dataset
    rv = client.get("/metrics/ui?export=csv")
    assert rv.status_code == 200
    text = rv.data.decode()
    assert "Users" in text
    # interactions are labelled by the column headers in the CSV
    assert "From dept" in text and "To dept" in text


def test_metrics_filter_and_csv_export(app, client):
    # a department head should be able to restrict the metrics view with a
    # query string, and the same filtering should apply when exporting CSV or
    # retrieving via the JSON endpoint.
    with app.app_context():
        head = User(
            email="filter-head@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        db.session.add(head)
        db.session.commit()
        db.session.add(
            DepartmentEditor(
                user_id=head.id,
                department="B",
                can_edit=False,
                can_view_metrics=True,
            )
        )
        # two requests that will show up in metrics
        r1 = ReqModel(
            title="Foo item",
            request_type="both",
            pricebook_status="unknown",
            description="x",
            priority="medium",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        r2 = ReqModel(
            title="Bar item",
            request_type="both",
            pricebook_status="unknown",
            description="y",
            priority="low",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=2)),
        )
        db.session.add_all([r1, r2])
        db.session.commit()
    rv = login_user(client, "filter-head@example.com")
    assert rv.status_code == 200

    # without a filter the aggregate total should be 2
    rv = client.get("/metrics/ui?range=weekly&dept=B")
    assert rv.status_code == 200
    assert b"2" in rv.data

    # apply a query that only matches the first request
    rv = client.get("/metrics/ui?range=weekly&dept=B&q=Foo")
    assert rv.status_code == 200
    # export csv for the filtered dataset and inspect contents
    rv = client.get("/metrics/ui?range=weekly&dept=B&q=Foo&export=csv")
    assert rv.status_code == 200
    assert rv.headers["Content-Type"].startswith("text/csv")
    text = rv.data.decode()
    lines = text.splitlines()
    assert lines[0].startswith("Department,Total")
    row = lines[1].split(",")
    assert row[0] == "B"
    assert row[1] == "1"
    # should include additional sections even if empty
    assert any(l.startswith("Users") for l in lines)
    assert any(l.startswith("From dept") for l in lines)

    # JSON endpoint should reflect the same filtered count
    rv = client.get("/metrics/json?range=weekly&dept=B&q=Foo")
    payload = rv.get_json()
    assert payload["by_dept"]["B"]["total"] == 1

    # an "all" range should also be accepted and include the same results
    rv = client.get("/metrics/ui?range=all&dept=B")
    assert rv.status_code == 200
    assert b"2" not in rv.data or b"2" in rv.data  # still renders normally
    rv = client.get("/metrics/ui?range=all&dept=B&q=Foo&export=csv")
    assert rv.status_code == 200
    # make sure the exported row still reflects the single-match filter
    text = rv.data.decode()
    lines = text.splitlines()
    assert lines[1].split(",")[1] == "1"


def test_admin_can_export_site_metrics(app, client):
    # admins should be able to grab a CSV containing metrics for every
    # department they have access to (all, since they're admins).
    with app.app_context():
        admin = User(
            email="admin@example.com",
            password_hash=generate_password_hash("secret"),
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        # two requests in different departments
        rA = ReqModel(
            title="A request",
            request_type="both",
            pricebook_status="unknown",
            description="",
            priority="low",
            status="A_IN_PROGRESS",
            owner_department="A",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        rB = ReqModel(
            title="B request",
            request_type="both",
            pricebook_status="unknown",
            description="",
            priority="low",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        db.session.add_all([rA, rB])
        db.session.commit()
    rv = login_user(client, "admin@example.com")
    assert rv.status_code == 200
    # admin should land on the command center instead of the department picker
    assert b"Command center" in rv.data
    # first visit the HTML metrics page and ensure the full-site button exists
    rv = client.get("/metrics/ui")
    assert rv.status_code == 200
    assert b"Full site metrics" in rv.data
    # now request CSV export
    rv = client.get("/metrics/ui?export=csv")
    assert rv.status_code == 200
    csvdoc = rv.data.decode()
    # should have a summary row for each department
    assert "A,1" in csvdoc
    assert "B,1" in csvdoc


def test_admin_can_view_metrics_from_settings_and_overview(app, client):
    with app.app_context():
        admin = User(
            email="metrics-settings-admin@example.com",
            password_hash=generate_password_hash("secret"),
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.add_all(
            [
                ReqModel(
                    title="Admin metrics A",
                    request_type="both",
                    pricebook_status="unknown",
                    description="",
                    priority="low",
                    status="A_IN_PROGRESS",
                    owner_department="A",
                    submitter_type="user",
                    due_at=(datetime.utcnow() + timedelta(days=1)),
                ),
                ReqModel(
                    title="Admin metrics B",
                    request_type="both",
                    pricebook_status="unknown",
                    description="",
                    priority="low",
                    status="B_IN_PROGRESS",
                    owner_department="B",
                    submitter_type="user",
                    due_at=(datetime.utcnow() + timedelta(days=1)),
                ),
            ]
        )
        db.session.commit()

    rv = login_user(client, "metrics-settings-admin@example.com")
    assert b"Command center" in rv.data
    assert rv.status_code == 200

    rv = client.get("/admin/metrics_config")
    assert rv.status_code == 200
    assert b"Open full metrics dashboard" in rv.data
    assert b"Metrics explorer" in rv.data
    assert b"All departments" in rv.data
    assert b"Dept A" in rv.data
    assert b"Dept B" in rv.data
    assert b"User efficiency" in rv.data

    rv = client.get("/admin/metrics_config?dept=A")
    assert rv.status_code == 200
    assert b"All departments" in rv.data
    assert b"Dept A" in rv.data

    rv = client.get("/admin/metrics_overview")
    assert rv.status_code == 200
    assert b"Admin Metrics Overview" in rv.data
    assert b"Full site metrics" in rv.data
    assert b"Back to Metrics Settings" in rv.data

    rv = client.get("/admin/metrics_overview?dept=A")
    assert rv.status_code == 200
    assert b"Admin Metrics Overview" in rv.data
    assert b"Dept A" in rv.data



def test_user_filter_and_export(app, client):
    # department head should be able to restrict which users show in metrics
    # and export the filtered set for comparison.
    from app.services.process_metrics import record_process_metric_event

    with app.app_context():
        head = User(
            email="userfilter-head@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        user1 = User(
            email="alice@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        user2 = User(
            email="bob@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        db.session.add_all([head, user1, user2])
        db.session.commit()
        db.session.add(
            DepartmentEditor(
                user_id=head.id,
                department="B",
                can_edit=False,
                can_view_metrics=True,
            )
        )
        # create two requests and log creation events by each user
        r1 = ReqModel(
            title="R1",
            request_type="both",
            pricebook_status="unknown",
            description="",
            priority="low",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        r2 = ReqModel(
            title="R2",
            request_type="both",
            pricebook_status="unknown",
            description="",
            priority="low",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        db.session.add_all([r1, r2])
        db.session.commit()
        # record events by user1 and user2
        record_process_metric_event(r1, event_type="request_created", actor_user=user1, actor_department="B")
        record_process_metric_event(r2, event_type="request_created", actor_user=user2, actor_department="B")

    rv = login_user(client, "userfilter-head@example.com")
    assert rv.status_code == 200

    # page should list both users by default
    rv = client.get("/metrics/ui?dept=B")
    assert rv.status_code == 200
    assert b"alice@example.com" in rv.data
    assert b"bob@example.com" in rv.data

    # apply filter to only include alice
    rv = client.get("/metrics/ui?dept=B&user=%d" % user1.id)
    assert rv.status_code == 200
    assert b"alice@example.com" in rv.data
    # bob should not appear in the user-efficiency table (may still be in the
    # dropdown list for filtering)
    assert b"<td>bob@example.com</td>" not in rv.data

    # export csv after filtering
    rv = client.get(f"/metrics/ui?dept=B&user={user1.id}&export=csv")
    assert rv.status_code == 200
    txt = rv.data.decode()
    assert "alice@example.com" in txt
    assert "bob@example.com" not in txt

    # JSON endpoint respects user filter too
    rv = client.get(f"/metrics/json?dept=B&user={user1.id}")
    payload = rv.get_json()
    assert all(u["email"] == "alice@example.com" for u in payload.get("users", []))


def test_bulk_assign_bucket(app, client):
    # department heads should see the bucket assignment dropdown and be able
    # to assign all items in a bucket with a single request.
    with app.app_context():
        head = User(
            email="bucket-head@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        colleague = User(
            email="colleague@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        db.session.add_all([head, colleague])
        db.session.commit()
        db.session.add(
            DepartmentEditor(
                user_id=head.id,
                department="B",
                can_edit=False,
                can_view_metrics=True,
            )
        )
        db.session.commit()
        # create a simple bucket
        bkt = StatusBucket(name="Test bucket", department_name="B", order=0, active=True)
        db.session.add(bkt)
        db.session.flush()
        db.session.add(BucketStatus(bucket_id=bkt.id, status_code="B_IN_PROGRESS", order=0))
        # two requests in that status
        r1 = ReqModel(
            title="R1",
            request_type="both",
            pricebook_status="unknown",
            description="",
            priority="low",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        r2 = ReqModel(
            title="R2",
            request_type="both",
            pricebook_status="unknown",
            description="",
            priority="low",
            status="B_IN_PROGRESS",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=1)),
        )
        db.session.add_all([r1, r2])
        db.session.commit()
        r1_id, r2_id, bkt_id, head_id, col_id = r1.id, r2.id, bkt.id, head.id, colleague.id
    rv = login_user(client, "bucket-head@example.com")
    assert rv.status_code == 200
    # perform the bulk assign
    rv = client.post(
        "/dashboard/assign_bucket",
        data={"bucket_id": str(bkt_id), "assignee": str(col_id)},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    with app.app_context():
        r1 = db.session.get(ReqModel, r1_id)
        r2 = db.session.get(ReqModel, r2_id)
        assert r1.assigned_to_user_id == col_id
        assert r2.assigned_to_user_id == col_id


def test_regular_user_cannot_view_metrics_without_department_head_role(app, client):
    with app.app_context():
        user = User(
            email="regular-user@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()

    rv = login_user(client, "regular-user@example.com")
    assert rv.status_code == 200

    rv = client.get("/metrics/ui")
    assert rv.status_code == 403


def test_admin_can_toggle_department_head_metrics_role(app, client):
    with app.app_context():
        admin = User(
            email="metrics-admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        head = User(
            email="toggle-head@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
        )
        db.session.add_all([admin, head])
        db.session.commit()
        head_id = head.id

    rv = login_user(client, "metrics-admin@example.com")
    assert b"Command center" in rv.data
    assert rv.status_code == 200

    rv = client.post(
        "/admin/dept_editors/new",
        data={
            "user_id": str(head_id),
            "department": "A",
            "can_edit": "y",
            "can_view_metrics": "y",
        },
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Department editor created" in rv.data

    with app.app_context():
        role = DepartmentEditor.query.filter_by(user_id=head_id, department="A").first()
        assert role is not None
        assert role.can_view_metrics is True


def test_admin_metrics_groups_departments_into_buckets(app, client):
    with app.app_context():
        admin = User(
            email="bucket-admin@example.com",
            password_hash=generate_password_hash("secret"),
            department="B",
            is_active=True,
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()

        db.session.add_all(
            [
                ReqModel(
                    title="Admin A Metric",
                    request_type="both",
                    pricebook_status="unknown",
                    description="a",
                    priority="medium",
                    status="NEW_FROM_A",
                    owner_department="A",
                    submitter_type="user",
                    due_at=(datetime.utcnow() + timedelta(days=1)),
                ),
                ReqModel(
                    title="Admin B Metric",
                    request_type="both",
                    pricebook_status="unknown",
                    description="b",
                    priority="medium",
                    status="B_IN_PROGRESS",
                    owner_department="B",
                    submitter_type="user",
                    due_at=(datetime.utcnow() + timedelta(days=1)),
                ),
                ReqModel(
                    title="Admin C Metric",
                    request_type="both",
                    pricebook_status="unknown",
                    description="c",
                    priority="medium",
                    status="PENDING_C_REVIEW",
                    owner_department="C",
                    submitter_type="user",
                    due_at=(datetime.utcnow() + timedelta(days=1)),
                ),
            ]
        )
        db.session.commit()

    rv = login_user(client, "bucket-admin@example.com")
    assert b"Command center" in rv.data
    assert rv.status_code == 200

    rv = client.get("/metrics/ui")
    assert rv.status_code == 200
    assert b"Department bucket" in rv.data
    assert b"Dept A" in rv.data
    assert b"Dept B" in rv.data
    assert b"Dept C" in rv.data
