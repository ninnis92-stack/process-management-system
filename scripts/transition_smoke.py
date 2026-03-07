"""Smoke test exercising transitions and handoffs (Dept A -> B -> C -> A flows).

Usage:
    PYTHONPATH=. .venv/bin/python scripts/transition_smoke.py

Creates users, submits a request as Dept A, then simulates Dept B and Dept C
handling the request and performs transitions to exercise handoff logic and
notifications.
"""

import os
from datetime import datetime, timedelta
import time

smoke_db_path = os.path.join(os.getcwd(), "test_smoke.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{smoke_db_path}")
os.environ.setdefault("WTF_CSRF_ENABLED", "False")

# Ensure a fresh smoke DB for this run
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
app.config["WTF_CSRF_ENABLED"] = False


def ensure_db():
    with app.app_context():
        db.create_all()

        def mk(email, dept):
            e = email.strip().lower()
            u = User.query.filter_by(email=e).first()
            if not u:
                u = User(
                    email=e,
                    name=e.split("@")[0],
                    department=dept,
                    is_active=True,
                    password_hash=generate_password_hash(
                        "password123", method="pbkdf2:sha256"
                    ),
                )
                db.session.add(u)
                db.session.commit()
            return u

        mk("a@example.com", "A")
        mk("b@example.com", "B")
        mk("c@example.com", "C")


def run_flow():
    ensure_db()
    # Create three separate clients to simulate different users
    client_a = app.test_client()
    client_b = app.test_client()
    client_c = app.test_client()

    # Login each
    def login(client, email):
        resp = client.post(
            "/auth/login",
            data={"email": email, "password": "password123"},
            follow_redirects=True,
        )
        if resp.status_code not in (200, 302):
            print(f"Login failed for {email}:", resp.status_code)
            return False
        return True

    assert login(client_a, "a@example.com")
    assert login(client_b, "b@example.com")
    assert login(client_c, "c@example.com")

    # A submits a request
    due = (datetime.utcnow() + timedelta(hours=72)).replace(second=0, microsecond=0)
    due_str = due.strftime("%Y-%m-%dT%H:%M")
    data = {
        "title": f"Transition Smoke {int(time.time())}",
        "request_type": "part_number",
        "donor_part_number": "D-999",
        "target_part_number": "T-999",
        "due_at": due_str,
        "pricebook_status": "unknown",
        "description": "Transition smoke test",
        "priority": "medium",
    }
    resp = client_a.post("/requests/new", data=data, follow_redirects=True)
    if resp.status_code >= 400:
        print("Failed to create request as A:", resp.status_code)
        return

    with app.app_context():
        req = ReqModel.query.order_by(ReqModel.id.desc()).first()
        req_id = req.id
    print("Created request", req_id)

    # B assigns to self
    resp = client_b.post(f"/requests/{req_id}/assign_self", follow_redirects=True)
    print("B assign_self ->", resp.status_code)

    # B transition to B_IN_PROGRESS
    resp = client_b.post(
        f"/requests/{req_id}/transition",
        data={"to_status": "B_IN_PROGRESS", "submission_summary": "Picking up work"},
        follow_redirects=True,
    )
    print("B -> B_IN_PROGRESS ->", resp.status_code)

    # B mark requires C review and send to pending
    resp = client_b.post(
        f"/requests/{req_id}/transition",
        data={
            "to_status": "PENDING_C_REVIEW",
            "requires_c_review": "y",
            "submission_summary": "Ready for C review",
        },
        follow_redirects=True,
    )
    print("B -> PENDING_C_REVIEW ->", resp.status_code)

    # C assign self
    resp = client_c.post(f"/requests/{req_id}/assign_self", follow_redirects=True)
    print("C assign_self ->", resp.status_code)

    # C approve (C_APPROVED)
    resp = client_c.post(
        f"/requests/{req_id}/transition",
        data={"to_status": "C_APPROVED", "submission_summary": "Approved by C"},
        follow_redirects=True,
    )
    print("C -> C_APPROVED ->", resp.status_code)

    # Check notifications for B (was actor) and for A (creator)
    resp = client_b.get("/notifications/unread_count")
    print("B unread notifications:", resp.get_json())
    resp = client_a.get("/notifications/unread_count")
    print("A unread notifications:", resp.get_json())


if __name__ == "__main__":
    run_flow()
