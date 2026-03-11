import pytest


def login(client, email="user@example.com", password="secret"):
    # clear existing session first
    client.get("/auth/logout", follow_redirects=True)
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_settings_page_includes_camera_demo(app, client):
    """The user settings page should render a demo input and camera button."""
    with app.app_context():
        # make sure a user exists
        from werkzeug.security import generate_password_hash

        from app.extensions import db
        from app.models import User

        u = User(
            email="user@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
        )
        db.session.add(u)
        db.session.commit()

    rv = login(client)
    assert rv.status_code == 200

    rv = client.get("/auth/settings")
    assert rv.status_code == 200
    assert b"Camera capture demo" in rv.data
    assert b"data-camera-target" in rv.data


def test_app_js_contains_camera_helpers(app, client):
    """Camera helpers should live in the frontend module source used by Vite."""
    with open("frontend/js/modules/camera.js", "rb") as handle:
        content = handle.read()
    assert b"attachCameraTrigger" in content
    assert b"sendCameraImage" in content
    assert b"appendCameraValue" in content
    assert b"template-prefill-run" in content


def test_request_form_shows_camera_for_verified_field(app, client):
    """A request template with a verified text field renders a camera button."""
    with app.app_context():
        from werkzeug.security import generate_password_hash

        from app.extensions import db

        # template model names
        from app.models import DepartmentFormAssignment, FormField, FormTemplate, User

        # create simple template and field
        tmpl = FormTemplate(name="camtest")
        db.session.add(tmpl)
        db.session.flush()
        fld = FormField(
            template_id=tmpl.id,
            name="serial",
            label="Serial",
            field_type="text",
            verification={"enabled": True},
        )
        db.session.add(fld)
        # assign template to department A so the form is available
        db.session.add(
            DepartmentFormAssignment(template_id=tmpl.id, department_name="A")
        )
        # add a regular user for test
        u = User(
            email="user@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
        )
        db.session.add(u)
        db.session.commit()
        user_id = u.id
    # manually mark user as logged in via session
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)

    rv = client.get("/requests/new", follow_redirects=True)
    assert rv.status_code == 200
    assert b"data-camera-target=" in rv.data
    # button should appear next to the input name serial
    assert b"[name='serial']" in rv.data


def test_request_form_shows_successive_camera_capture_for_bulk_verified_field(
    app, client
):
    """Bulk-verified fields should render additive camera capture affordances."""
    with app.app_context():
        from werkzeug.security import generate_password_hash

        from app.extensions import db
        from app.models import DepartmentFormAssignment, FormField, FormTemplate, User

        tmpl = FormTemplate(name="bulkcam", verification_prefill_enabled=True)
        db.session.add(tmpl)
        db.session.flush()
        fld = FormField(
            template_id=tmpl.id,
            name="part_numbers",
            label="Part numbers",
            field_type="text",
            verification={
                "provider": "verification",
                "external_key": "sku",
                "params": {
                    "verify_each_separated_value": True,
                    "value_separator": "newline",
                    "bulk_input_hint": "Scan each item one at a time",
                },
            },
        )
        db.session.add(fld)
        db.session.add(
            DepartmentFormAssignment(template_id=tmpl.id, department_name="A")
        )
        u = User(
            email="bulkcam@example.com",
            password_hash=generate_password_hash("secret"),
            department="A",
            is_active=True,
            is_admin=False,
        )
        db.session.add(u)
        db.session.commit()
        user_id = u.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)

    rv = client.get("/requests/new", follow_redirects=True)
    assert rv.status_code == 200
    assert b"Multi-value scan" in rv.data
    assert b'data-camera-mode="append"' in rv.data
    assert b'data-camera-separator="newline"' in rv.data
    assert b"Add scan" in rv.data
    assert b"Scan each item in sequence." in rv.data


def test_camera_endpoint_ocr(app, client, monkeypatch):
    """The /verify/camera route should return OCR text when given an image.

    Since the test environment may not have the `tesseract` binary installed we
    patch ``pytesseract.image_to_string`` to avoid spawning a subprocess. The
    production code still calls the real function; this just makes the test
    reliable in CI and local dev where the binary might be missing.
    """
    # stub OCR routine
    try:
        import pytesseract
    except ImportError:
        pytesseract = None

    if pytesseract:
        monkeypatch.setattr(
            pytesseract, "image_to_string", lambda img, config=None: "ABC123"
        )

    # create a simple image with text using PIL
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (200, 60), color="white")
    d = ImageDraw.Draw(img)
    # use default font
    d.text((10, 10), "ABC123", fill="black")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)

    data = {"image": (buf, "test.jpg"), "field": "demo_field"}
    rv = client.post("/verify/camera", data=data, content_type="multipart/form-data")
    assert rv.status_code == 200
    json = rv.get_json()
    assert json["ok"] is True
    assert json["field"] == "demo_field"
    # OCR might uppercase/lowercase; we expect alphanumerics match
    assert "ABC" in json["value"].upper()
    assert "123" in json["value"]
