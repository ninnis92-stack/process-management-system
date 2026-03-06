import pytest
from werkzeug.security import generate_password_hash
from app.models import User, FormTemplate, FormField, DepartmentFormAssignment, FieldVerification, Submission, Attachment
from app.extensions import db


class DummyInv:
    def validate_part_number(self, pn):
        return pn == 'VALID123'
    def validate_sales_list_number(self, n):
        return n == 'SKU-1'


def test_field_verification_inventory(app, client, monkeypatch):
    # create a user in Dept A and login
    u = User(email='verifier@example.com', name='Verifier', department='A', is_active=True, password_hash=generate_password_hash('password'))
    db.session.add(u)
    db.session.commit()

    rv = client.post('/auth/login', data={'email': 'verifier@example.com', 'password': 'password'}, follow_redirects=True)
    assert rv.status_code in (200, 302)

    # create template with a field
    t = FormTemplate(name='InvTemplate', description='Inventory test')
    db.session.add(t)
    db.session.commit()
    f = FormField(template_id=t.id, name='donor_part_number', label='Donor PN', field_type='text', required=True)
    db.session.add(f)
    db.session.commit()

    # assign to Dept A
    a = DepartmentFormAssignment(template_id=t.id, department_name='A')
    db.session.add(a)
    db.session.commit()

    # map field to inventory provider
    fv = FieldVerification(field_id=f.id, provider='inventory', external_key='donor_part_number')
    db.session.add(fv)
    db.session.commit()

    # enable external verification for the test and monkeypatch the InventoryService
    app.config['ENABLE_EXTERNAL_VERIFICATION'] = True
    from app.requests_bp.routes import InventoryService
    monkeypatch.setattr('app.requests_bp.routes.InventoryService', lambda: DummyInv())

    # submit valid PN -> should pass verification
    data = {'donor_part_number': 'VALID123', 'due_at': '2030-01-01'}
    rv = client.post('/requests/new', data=data, follow_redirects=True)
    assert rv.status_code in (200, 302)

    # check latest submission has verification ok
    sub = Submission.query.order_by(Submission.created_at.desc()).first()
    assert sub is not None
    assert sub.data.get('_verifications', {}).get('donor_part_number', {}).get('ok') is True

    # submit invalid PN -> verification false
    data = {'donor_part_number': 'BAD', 'due_at': '2030-01-01'}
    rv = client.post('/requests/new', data=data, follow_redirects=True)
    assert rv.status_code in (200, 302)
    sub2 = Submission.query.order_by(Submission.created_at.desc()).first()
    assert sub2 is not None
    assert sub2.data.get('_verifications', {}).get('donor_part_number', {}).get('ok') is False
