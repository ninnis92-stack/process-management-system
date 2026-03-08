import io
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from app.models import (
    User,
    FormTemplate,
    FormField,
    FormFieldOption,
    DepartmentFormAssignment,
    Submission,
    Attachment,
)


def test_dynamic_submission_with_file_and_regex(app, client):
    # Create a user in Dept A and log in
    u = User(
        email="testa@example.com",
        name="Tester A",
        department="A",
        is_active=True,
        password_hash=generate_password_hash("password"),
    )
    from app.extensions import db

    db.session.add(u)
    db.session.commit()

    # login
    rv = client.post(
        "/auth/login",
        data={"email": "testa@example.com", "password": "password"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    # Create a template with a text field (with regex) and a file field
    t = FormTemplate(name="Quick Template", description="Used in tests")
    db.session.add(t)
    db.session.commit()

    f1 = FormField(
        template_id=t.id,
        name="person_name",
        label="Name",
        field_type="text",
        required=True,
        verification={"type": "regex", "pattern": r"^[A-Za-z ]{2,100}$"},
    )
    f2 = FormField(
        template_id=t.id,
        name="screenshot",
        label="Screenshot",
        field_type="file",
        required=False,
    )
    db.session.add(f1)
    db.session.add(f2)
    db.session.commit()

    # assign to Dept A
    a = DepartmentFormAssignment(template_id=t.id, department_name="A")
    db.session.add(a)
    db.session.commit()

    # Post a dynamic submission with a valid name and a small file
    due_dt = (datetime.utcnow() + timedelta(days=3)).isoformat()
    data = {
        "person_name": "Jane Doe",
        "due_at": due_dt,
    }
    data_files = {"screenshot": (io.BytesIO(b"PNGDATA"), "screenshot.png")}

    # Merge files into data for multipart posting
    multipart = dict(data)
    multipart.update({"screenshot": data_files["screenshot"]})

    rv = client.post(
        "/requests/new",
        data=multipart,
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    # Inspect DB for created submission and attachment
    req = Submission.query.order_by(Submission.created_at.desc()).first()
    assert req is not None
    assert req.data.get("person_name") == "Jane Doe"
    # verification results should be attached
    assert req.data.get("_verifications") is not None
    assert req.data["_verifications"].get("person_name", {}).get("ok") is True

    # ensure attachment exists
    att = Attachment.query.filter_by(submission_id=req.id).first()
    assert att is not None
    assert att.original_filename == "screenshot.png"


def test_conditional_requirement_makes_target_field_required(app, client):
    u = User(
        email="conditional@example.com",
        name="Conditional",
        department="A",
        is_active=True,
        password_hash=generate_password_hash("password"),
    )
    from app.extensions import db

    db.session.add(u)
    db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "conditional@example.com", "password": "password"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    t = FormTemplate(name="Conditional Template", description="Conditional rule test")
    db.session.add(t)
    db.session.commit()

    trigger = FormField(
        template_id=t.id,
        name="request_reason",
        label="Request Reason",
        field_type="text",
        required=False,
        section_name="Primary details",
    )
    dependent = FormField(
        template_id=t.id,
        name="supporting_context",
        label="Supporting Context",
        field_type="textarea",
        required=False,
        section_name="Follow-up",
        requirement_rules={
            "enabled": True,
            "scope": "field",
            "mode": "all",
            "message": "Supporting Context is required once Request Reason is populated.",
            "rules": [
                {"source_type": "field", "source": "request_reason", "operator": "populated"}
            ],
        },
    )
    db.session.add_all([trigger, dependent])
    db.session.commit()

    db.session.add(DepartmentFormAssignment(template_id=t.id, department_name="A"))
    db.session.commit()

    rv = client.get("/requests/new")
    assert rv.status_code == 200
    assert b"Configured section" in rv.data
    assert b"Required when request_reason is filled in" in rv.data
    # the new JS hint container should also be present (initially hidden)
    assert b"requirement-hint" in rv.data
    assert b"data-section-progress-label" in rv.data

    rv = client.post(
        "/requests/new",
        data={"request_reason": "Need expedited handling", "due_at": "2030-01-01"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Supporting Context is required once Request Reason is populated." in rv.data

    rv = client.post(
        "/requests/new",
        data={
            "request_reason": "Need expedited handling",
            "supporting_context": "Customer deadline confirmed.",
            "due_at": "2030-01-01",
        },
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)


def test_conditional_section_requirement_can_require_upload_section(app, client):
    u = User(
        email="uploadreq@example.com",
        name="Upload Requirement",
        department="A",
        is_active=True,
        password_hash=generate_password_hash("password"),
    )
    from app.extensions import db

    db.session.add(u)
    db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "uploadreq@example.com", "password": "password"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    t = FormTemplate(name="Upload Rule Template", description="Upload requirement test")
    db.session.add(t)
    db.session.commit()

    trigger = FormField(
        template_id=t.id,
        name="request_type_detail",
        label="Request Type Detail",
        field_type="text",
        required=False,
        section_name="Primary details",
    )
    upload_field = FormField(
        template_id=t.id,
        name="supporting_file",
        label="Supporting File",
        field_type="file",
        required=False,
        section_name="Supporting uploads",
        requirement_rules={
            "enabled": True,
            "scope": "section",
            "mode": "all",
            "message": "Upload the supporting files section when Request Type Detail equals requires_upload.",
            "rules": [
                {"source_type": "field", "source": "request_type_detail", "operator": "equals", "value": "requires_upload"}
            ],
        },
    )
    db.session.add_all([trigger, upload_field])
    db.session.commit()

    db.session.add(DepartmentFormAssignment(template_id=t.id, department_name="A"))
    db.session.commit()

    rv = client.post(
        "/requests/new",
        data={"request_type_detail": "requires_upload", "due_at": "2030-01-01"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Upload the supporting files section when Request Type Detail equals requires_upload." in rv.data

    rv = client.post(
        "/requests/new",
        data={
            "request_type_detail": "requires_upload",
            "supporting_file": (io.BytesIO(b"PDFDATA"), "evidence.pdf"),
            "due_at": "2030-01-01",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)
