import io
from werkzeug.security import generate_password_hash
from app.models import User, FormTemplate, FormField, DepartmentFormAssignment


def test_admin_requirement_builder_ui_and_save(app, client):
    # create an admin user and log in
    u = User(
        email="adminreq@example.com",
        name="Admin Req",
        department="A",
        is_active=True,
        is_admin=True,
        password_hash=generate_password_hash("password"),
    )
    from app.extensions import db

    db.session.add(u)
    db.session.commit()

    rv = client.post(
        "/auth/login",
        data={"email": "adminreq@example.com", "password": "password"},
        follow_redirects=True,
    )
    assert rv.status_code in (200, 302)

    # create a template and two simple fields
    t = FormTemplate(name="AdminReqTemplate", description="Test admin builder")
    db.session.add(t)
    db.session.commit()
    template_id = t.id

    trigger = FormField(
        template_id=t.id,
        name="trigger_field",
        label="Trigger Field",
        field_type="text",
        required=False,
    )
    dependent = FormField(
        template_id=t.id,
        name="dependent_field",
        label="Dependent Field",
        field_type="text",
        required=False,
    )
    db.session.add_all([trigger, dependent])
    db.session.commit()

    db.session.add(DepartmentFormAssignment(template_id=t.id, department_name="A"))
    db.session.commit()

    # GET the requirements page and ensure builder UI is present
    rv = client.get(f"/admin/fields/{dependent.id}/requirements")
    assert rv.status_code == 200
    assert b'id="requirementBuilder"' in rv.data
    assert b'Field: Trigger Field' in rv.data

    rv_grouped = client.get(f"/admin/templates/{template_id}/fields")
    assert rv_grouped.status_code == 200
    assert b'admin-field-group' in rv_grouped.data
    assert b'Ungrouped fields' in rv_grouped.data

    # POST a simple rule using the hidden JSON field (simulating builder output)
    rv2 = client.post(
        f"/admin/fields/{dependent.id}/requirements",
        data={
            "enabled": "y",
            "scope": "field",
            "mode": "all",
            "message": "Required when trigger is filled.",
            "rules_json": "[{\"source_type\": \"field\", \"source\": \"trigger_field\", \"operator\": \"populated\"}]",
        },
        follow_redirects=True,
    )
    assert rv2.status_code == 200
    assert b"Conditional requirement rules saved" in rv2.data

    # the DB record should now reflect the rule config
    dep = db.session.get(FormField, dependent.id)
    assert dep.requirement_rules and dep.requirement_rules.get('enabled')
    assert dep.requirement_rules.get('rules')[0]['operator'] == 'populated'


def test_template_layout_persistence_and_api(app, client):
    import importlib
    import api.index as api_index

    # create admin user
    u = User(
        email="templatelayout@example.com",
        name="Layout Admin",
        department="A",
        is_active=True,
        is_admin=True,
        password_hash=generate_password_hash("password"),
    )
    from app.extensions import db

    db.session.add(u)
    db.session.commit()
    client.post(
        "/auth/login",
        data={"email": "templatelayout@example.com", "password": "password"},
        follow_redirects=True,
    )
    # create a template with non-default layout
    t = FormTemplate(name="LayoutTemplate", description="Layout test", layout="spacious")
    db.session.add(t)
    db.session.commit()
    with app.test_client() as api_client:
        api_index = importlib.reload(api_index)
        api_app = api_index.app
        with api_app.app_context():
            db.create_all()
        api = api_app.test_client()
        headers = {"X-Api-Key": "test-key"}
        rv = api.get("/api/templates", headers=headers)
        data = rv.get_json()
        # find our template
        found = next((x for x in data.get("templates", []) if x.get("id") == t.id), None)
        assert found is not None
        assert found.get("layout") == "spacious"

    # visit the request_new page with this template assigned to Dept A
    with app.app_context():
        db.session.add(DepartmentFormAssignment(template_id=t.id, department_name="A"))
        db.session.commit()
    rv2 = client.get("/requests/new")
    html2 = rv2.get_data(as_text=True)
    assert "template-layout-spacious" in html2
