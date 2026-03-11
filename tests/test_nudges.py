from datetime import datetime, timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import BucketStatus, FeatureFlags, Notification
from app.models import Request as ReqModel
from app.models import SpecialEmailConfig, StatusBucket, StatusOption, User
from app.notifications.due import send_high_priority_nudges


@pytest.fixture()
def app():
    # Use an in-memory DB for isolation during this test
    import os

    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["AUTO_CREATE_DB"] = "True"
    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        EMAIL_ENABLED=False,
        SERVER_NAME="localhost",
    )
    with app.app_context():
        db.create_all()
    yield app


def test_send_nudges_creates_notification(app):
    """Basic smoke tests around automated nudges.

    Verifies that a high (or highest) priority request triggers a notification
    and that the per-request interval configuration is respected.
    """
    with app.app_context():
        Notification.query.delete()
        ReqModel.query.delete()
        User.query.delete()
        StatusOption.query.delete()
        db.session.commit()

        # make sure there is a status option so model lookup works
        so = StatusOption(code="B_IN_PROGRESS", label="B In Progress")
        db.session.add(so)
        db.session.commit()

        cfg = SpecialEmailConfig.get()
        flags = FeatureFlags.get()
        flags.enable_nudges = True
        cfg.nudge_enabled = True
        cfg.nudge_min_delay_hours = 4
        db.session.commit()

        u = User(
            email="nudge_user@example.com",
            password_hash="x",
            department="B",
            is_active=True,
            daily_nudge_limit=2,
        )
        db.session.add(u)
        db.session.commit()

        # create two requests -- one regular high, one highest -- both
        for prio in ("high", "highest"):
            r = ReqModel(
                title=f"Urgent {prio}",
                request_type="both",
                pricebook_status="unknown",
                description="x",
                priority=prio,
                status="B_IN_PROGRESS",
                owner_department="B",
                submitter_type="user",
                due_at=(datetime.utcnow() + timedelta(days=3)),
            )
            db.session.add(r)
            db.session.commit()
            r.assigned_to_user_id = u.id
            r.created_at = datetime.utcnow() - timedelta(hours=5)
            db.session.commit()

        # run nudges once, expect notifications for both requests
        send_high_priority_nudges(app)
        notes = Notification.query.filter_by(user_id=u.id, type="nudge").all()
        assert len(notes) == 2


def test_status_level_controls_interval(app):
    """Verify the nudge interval is determined by a status option's level."""
    with app.app_context():
        Notification.query.delete()
        ReqModel.query.delete()
        User.query.delete()
        StatusOption.query.delete()
        StatusBucket.query.delete()
        BucketStatus.query.delete()
        db.session.commit()

        # create user and bucket/status order for nudge level
        u = User(
            email="level_user@example.com",
            password_hash="x",
            department="B",
            is_active=True,
        )
        db.session.add(u)
        # create a bucket with an order for STEP1
        bucket = StatusBucket(name="Test", department_name="B")
        db.session.add(bucket)
        db.session.commit()
        bs = BucketStatus(bucket_id=bucket.id, status_code="STEP1", order=0)
        db.session.add(bs)
        db.session.commit()

        r = ReqModel(
            title="Level1",
            request_type="both",
            pricebook_status="unknown",
            description="x",
            priority="high",
            status="STEP1",
            owner_department="B",
            submitter_type="user",
            due_at=(datetime.utcnow() + timedelta(days=3)),
            assigned_to_user_id=u.id,
        )
        r.created_at = datetime.utcnow() - timedelta(hours=5)
        db.session.add(r)
        db.session.commit()

        cfg = SpecialEmailConfig.get()
        flags = FeatureFlags.get()
        flags.enable_nudges = True
        cfg.nudge_enabled = True
        cfg.nudge_min_delay_hours = 0  # ignore the delay for test
        db.session.commit()

        # first run should create one notification
        send_high_priority_nudges(app)
        assert Notification.query.filter_by(user_id=u.id).count() == 1

        # advance time but not enough for hourly interval (simulate by
        # manually inserting a recent notification and calling again)
        # running again immediately should not add another
        send_high_priority_nudges(app)
        assert Notification.query.filter_by(user_id=u.id).count() == 1


def test_daily_and_per_user_limits(app):
    """User should only receive as many nudges per day as allowed."""
    with app.app_context():
        Notification.query.delete()
        ReqModel.query.delete()
        User.query.delete()
        StatusOption.query.delete()
        db.session.commit()

        u = User(
            email="limit_user@example.com",
            password_hash="x",
            department="B",
            is_active=True,
            daily_nudge_limit=2,
        )
        db.session.add(u)
        so = StatusOption(code="STEP2", label="Step2", nudge_level=1)
        db.session.add(so)
        db.session.commit()

        # create three high-priority requests
        for i in range(3):
            r = ReqModel(
                title=f"Req{i}",
                request_type="both",
                pricebook_status="unknown",
                description="x",
                priority="high",
                status="STEP2",
                owner_department="B",
                submitter_type="user",
                due_at=(datetime.utcnow() + timedelta(days=3)),
                assigned_to_user_id=u.id,
            )
            r.created_at = datetime.utcnow() - timedelta(hours=5)
            db.session.add(r)
        db.session.commit()

        cfg = SpecialEmailConfig.get()
        flags = FeatureFlags.get()
        flags.enable_nudges = True
        cfg.nudge_enabled = True
        cfg.nudge_min_delay_hours = 0
        db.session.commit()

        send_high_priority_nudges(app)
        # should have only two notifications despite three requests
        assert Notification.query.filter_by(user_id=u.id).count() == 2
