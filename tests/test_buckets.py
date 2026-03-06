import pytest
from app.extensions import db
from app.models import User, Request as ReqModel, StatusBucket, BucketStatus
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta


def login_admin(client, email='admin@example.com', password='secret'):
    return client.post('/auth/login', data={'email': email, 'password': password}, follow_redirects=True)


def test_bucket_import_and_filtering(app, client):
    # Setup admin user and some requests
    with app.app_context():
        # create admin user
        u = User(email='admin@example.com', password_hash=generate_password_hash('secret'), department='B', is_active=True, is_admin=True)
        db.session.add(u)
        db.session.commit()

        # create a couple of requests
        r1 = ReqModel(title='Progress Item', request_type='both', pricebook_status='unknown', description='x', priority='medium', status='B_IN_PROGRESS', owner_department='B', submitter_type='user', due_at=(datetime.utcnow()+timedelta(days=2)))
        r2 = ReqModel(title='Needs Input Item', request_type='both', pricebook_status='unknown', description='y', priority='low', status='WAITING_ON_A_RESPONSE', owner_department='B', submitter_type='user', due_at=(datetime.utcnow()+timedelta(days=5)))
        db.session.add_all([r1, r2])
        db.session.commit()

    # login as admin
    rv = login_admin(client)
    assert rv.status_code == 200

    # import default buckets
    rv = client.post('/admin/buckets/import_default', follow_redirects=True)
    assert b'Imported recommended buckets' in rv.data

    # find the 'In Progress' bucket id
    with app.app_context():
        in_progress = StatusBucket.query.filter_by(name='In Progress', department_name='B').first()
        assert in_progress is not None
        # ensure it maps to B_IN_PROGRESS
        codes = [s.status_code for s in in_progress.statuses.all()]
        assert 'B_IN_PROGRESS' in codes

    # request dashboard filtered by bucket_id
    rv = client.get(f'/dashboard?bucket_id={in_progress.id}')
    assert rv.status_code == 200
    # should include the Progress Item
    assert b'Progress Item' in rv.data
    # should not include the Needs Input Item in this bucket
    assert b'Needs Input Item' not in rv.data
