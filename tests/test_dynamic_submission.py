import io
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from app.models import User, FormTemplate, FormField, FormFieldOption, DepartmentFormAssignment, Submission, Attachment


def test_dynamic_submission_with_file_and_regex(app, client):
    # Create a user in Dept A and log in
    u = User(email='testa@example.com', name='Tester A', department='A', is_active=True,
             password_hash=generate_password_hash('password'))
    from app.extensions import db
    db.session.add(u)
    db.session.commit()

    # login
    rv = client.post('/auth/login', data={'email': 'testa@example.com', 'password': 'password'}, follow_redirects=True)
    assert rv.status_code in (200, 302)

    # Create a template with a text field (with regex) and a file field
    t = FormTemplate(name='Quick Template', description='Used in tests')
    db.session.add(t)
    db.session.commit()

    f1 = FormField(template_id=t.id, name='person_name', label='Name', field_type='text', required=True, verification={'type': 'regex', 'pattern': r"^[A-Za-z ]{2,100}$"})
    f2 = FormField(template_id=t.id, name='screenshot', label='Screenshot', field_type='file', required=False)
    db.session.add(f1)
    db.session.add(f2)
    db.session.commit()

    # assign to Dept A
    a = DepartmentFormAssignment(template_id=t.id, department_name='A')
    db.session.add(a)
    db.session.commit()

    # Post a dynamic submission with a valid name and a small file
    due_dt = (datetime.utcnow() + timedelta(days=3)).isoformat()
    data = {
        'person_name': 'Jane Doe',
        'due_at': due_dt,
    }
    data_files = {
        'screenshot': (io.BytesIO(b'PNGDATA'), 'screenshot.png')
    }

    # Merge files into data for multipart posting
    multipart = dict(data)
    multipart.update({'screenshot': data_files['screenshot']})

    rv = client.post('/requests/new', data=multipart, content_type='multipart/form-data', follow_redirects=True)
    assert rv.status_code in (200, 302)

    # Inspect DB for created submission and attachment
    req = Submission.query.order_by(Submission.created_at.desc()).first()
    assert req is not None
    assert req.data.get('person_name') == 'Jane Doe'
    # verification results should be attached
    assert req.data.get('_verifications') is not None
    assert req.data['_verifications'].get('person_name', {}).get('ok') is True

    # ensure attachment exists
    att = Attachment.query.filter_by(submission_id=req.id).first()
    assert att is not None
    assert att.original_filename == 'screenshot.png'
