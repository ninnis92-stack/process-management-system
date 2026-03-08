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
