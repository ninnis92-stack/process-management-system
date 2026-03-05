from datetime import datetime, timedelta
import os
from app import create_app
from app.extensions import db
from app.models import Request as Req

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['AUTO_CREATE_DB'] = 'True'
app = create_app()
app.con***REMOVED***g.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})
with app.app_context():
    db.create_all()
    client = app.test_client()
    due = (datetime.utcnow() + timedelta(hours=72)).strftime('%Y-%m-%dT%H:%M')
    resp = client.post('/external/new', data={
        'guest_email': 'guest@example.com',
        'guest_name': 'Guesty',
        'title': 'Need help',
        'request_type': 'part_number',
        'donor_part_number': '',
        'target_part_number': 'ABC',
        'no_donor_reason': 'needs_create',
        'pricebook_status': 'unknown',
        'priority': 'medium',
        'due_at': due,
        'description': '',
    }, follow_redirects=False)
    print('POST status', resp.status_code, 'Location', resp.headers.get('Location'))
    print('Request count:', Req.query.count())
    for r in Req.query.all():
        print('REQ', r.id, r.title, r.description)
