import pytest
from app import create_app
from app.extensions import db
from app.models import User, Request as ReqModel, Notification, SpecialEmailConfig
from app.notifications.due import send_high_priority_nudges


@pytest.fixture()
def app():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, EMAIL_ENABLED=False)
    with app.app_context():
        db.create_all()
    yield app


def test_send_nudges_creates_notification(app):
    with app.app_context():
        # ensure config
        cfg = SpecialEmailConfig.get()
        cfg.nudge_enabled = True
        cfg.nudge_interval_hours = 1
        db.session.commit()

        # create user and high-priority request
        u = User(email='nudge_test@example.com', password_hash='x', department='B', is_active=True)
        db.session.add(u)
        db.session.commit()

        r = ReqModel(title='Urgent', request_type='both', pricebook_status='unknown', description='x', priority='high', status='B_IN_PROGRESS', owner_department='B', submitter_type='user', due_at=None)
        db.session.add(r)
        db.session.commit()

        # assign to user
        r.assigned_to_user_id = u.id
        db.session.commit()

        # run nudges
        send_high_priority_nudges(app)

        n = Notification.query.filter_by(user_id=u.id, type='nudge', request_id=r.id).first()
        assert n is not None