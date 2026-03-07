"""Automated smoke script for role-based flow (Dept A -> create request -> notification).

Usage:
    python scripts/automated_role_smoke.py

The script creates a temporary SQLite DB file `test_smoke.db` in the repo root,
creates users, logs in via the Flask test client, submits a new request, and
prints the resulting notification unread count and created request id.

This is intended for local development only.
"""
import os
import time
from datetime import datetime, timedelta
import json

# Force a local sqlite DB for the smoke run (use absolute path)
smoke_db_path = os.path.join(os.getcwd(), 'test_smoke.db')
os.environ.setdefault('DATABASE_URL', f"sqlite:///{smoke_db_path}")
# Disable CSRF validation for automated test client usage
os.environ.setdefault('WTF_CSRF_ENABLED', 'False')

# Remove any existing smoke DB so we start with a fresh schema for this run.
try:
    if os.path.exists(smoke_db_path):
        os.remove(smoke_db_path)
except Exception:
    pass

from app import create_app
from app.extensions import db
from werkzeug.security import generate_password_hash
from app.models import User, Request as ReqModel, Notification

app = create_app()
# Ensure Flask-WTF CSRF is off (safety)
app.config['WTF_CSRF_ENABLED'] = False


def ensure_db():
    with app.app_context():
        db.create_all()

        # If running against an existing sqlite DB created before the
        # `last_active_dept` column was added, add it now so smoke runs
        # don't fail. This is a development-only safety step.
        try:
            # Use the session/connection to inspect/alter sqlite schema (best-effort)
            url = str(db.session.get_bind().engine.url)
            if 'sqlite' in url:
                res = db.session.execute("PRAGMA table_info('user')")
                cols = [row[1] for row in res.fetchall()]
                if 'last_active_dept' not in cols:
                    db.session.execute("ALTER TABLE user ADD COLUMN last_active_dept VARCHAR")
                    db.session.commit()
        except Exception:
            # best-effort only; ignore failures
            try:
                db.session.rollback()
            except Exception:
                pass

        # Create test users if they don't exist
        def mk(email, dept):
            e = email.strip().lower()
            u = User.query.filter_by(email=e).first()
            if not u:
                u = User(email=e, name=e.split('@')[0], department=dept, is_active=True,
                         password_hash=generate_password_hash('password123', method='pbkdf2:sha256'))
                db.session.add(u)
                db.session.commit()
            return u

        mk('a@example.com', 'A')
        mk('b@example.com', 'B')
        mk('c@example.com', 'C')
        mk('admin@example.com', 'B')


def run_smoke():
    ensure_db()

    client = app.test_client()

    # Login as Dept A user
    resp = client.post('/auth/login', data={'email': 'a@example.com', 'password': 'password123'}, follow_redirects=True)
    if resp.status_code not in (200, 302):
        print('Login failed:', resp.status_code)
        return

    # Prepare due_at (48+ hours) in the expected format: %Y-%m-%dT%H:%M
    due = (datetime.utcnow() + timedelta(hours=72)).replace(second=0, microsecond=0)
    due_str = due.strftime('%Y-%m-%dT%H:%M')

    # Submit a new request (Dept A submitter)
    data = {
        'title': f'Test request {int(time.time())}',
        'request_type': 'part_number',
        'donor_part_number': 'D-123',
        'target_part_number': 'T-456',
        'no_donor_reason': '',
        'due_at': due_str,
        'pricebook_status': 'unknown',
        'sales_list_reference': '',
        'description': 'Automated smoke test submission',
        'priority': 'medium',
    }

    resp = client.post('/requests/new', data=data, follow_redirects=True)
    if resp.status_code >= 400:
        print('Failed to create request:', resp.status_code)
        return

    # Query DB to find the latest created request
    with app.app_context():
        req = ReqModel.query.order_by(ReqModel.id.desc()).first()
        if not req:
            print('No request found after submission')
            return
        req_id = req.id

    # Check unread notification count for the logged-in user
    resp = client.get('/notifications/unread_count')
    try:
        j = resp.get_json()
    except Exception:
        j = None

    print('Created request id:', req_id)
    print('Unread notifications endpoint returned:', j)


if __name__ == '__main__':
    run_smoke()
