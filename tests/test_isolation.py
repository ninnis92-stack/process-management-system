from werkzeug.security import generate_password_hash
from app.extensions import db
from app.models import User, Request as ReqModel
from datetime import datetime, timedelta


def login(client, email, password='secret'):
    return client.post('/auth/login', data={'email': email, 'password': password}, follow_redirects=True)


def test_enforce_dept_isolation(app, client):
    with app.app_context():
        app.config['ENFORCE_DEPT_ISOLATION'] = True
        # create users
        a = User(email='a_user@example.com', password_hash=generate_password_hash('secret'), department='A', is_active=True)
        b = User(email='b_user@example.com', password_hash=generate_password_hash('secret'), department='B', is_active=True)
        db.session.add_all([a, b])
        db.session.commit()

        # create a request owned by B
        r = ReqModel(title='B Item', request_type='both', pricebook_status='unknown', description='x', priority='medium', status='B_IN_PROGRESS', owner_department='B', submitter_type='user', due_at=(datetime.utcnow() + timedelta(days=2)))
        r.created_by_user_id = b.id
        db.session.add(r)
        db.session.commit()
        rid = r.id

    # login as A and attempt to view -> should be forbidden
    rv = login(client, 'a_user@example.com')
    assert rv.status_code == 200
    resp = client.get(f'/requests/{rid}')
    assert resp.status_code == 403

    # login as B and view -> allowed
    client.get('/auth/logout')
    rv = login(client, 'b_user@example.com')
    assert rv.status_code == 200
    resp = client.get(f'/requests/{rid}')
    assert resp.status_code == 200
