from app import create_app
from app.extensions import db
from app.models import User, Notification
from app.notifcations import notify_users

app = create_app()
with app.app_context():
    # Ensure test users exist
    u1 = User.query.filter_by(email='test_email_user@example.com').first()
    if not u1:
        u1 = User(email='test_email_user@example.com', password_hash='x', department='A')
        db.session.add(u1)
    # The User.email column is NOT NULL in this schema; use an empty-string
    # to represent a user without a usable email address for testing.
    u2 = User.query.filter_by(email='').first()
    if not u2:
        u2 = User(email='', password_hash='x', department='A')
        db.session.add(u2)
    db.session.commit()

    # cleanup
    Notification.query.filter(Notification.user_id.in_([u1.id, u2.id])).delete()
    db.session.commit()

    print('EMAIL_ENABLED before:', app.config.get('EMAIL_ENABLED'))

    app.config['EMAIL_ENABLED'] = False
    notify_users([u1, u2], 'Test Title', body='test body', url='http://example.com', ntype='test')
    db.session.commit()
    c1 = Notification.query.filter_by(user_id=u1.id).count()
    c2 = Notification.query.filter_by(user_id=u2.id).count()
    print('With EMAIL_ENABLED=False -> counts:', c1, c2)

    # Now enable email
    Notification.query.filter(Notification.user_id.in_([u1.id, u2.id])).delete()
    db.session.commit()

    app.config['EMAIL_ENABLED'] = True
    notify_users([u1, u2], 'Test Title 2', body='test body 2', url='http://example.com', ntype='test')
    db.session.commit()
    c1 = Notification.query.filter_by(user_id=u1.id).count()
    c2 = Notification.query.filter_by(user_id=u2.id).count()
    print('With EMAIL_ENABLED=True -> counts:', c1, c2)
