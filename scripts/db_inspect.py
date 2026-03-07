from app import create_app
from app.extensions import db
from app.models import Notification, User

app = create_app()
with app.app_context():
    print("DB URI:", app.config["SQLALCHEMY_DATABASE_URI"])
    print("Users:", User.query.count())
    print("Notifications:", Notification.query.count())
    for n in Notification.query.limit(10).all():
        print(n.id, n.user_id, n.title, n.is_read, n.created_at)
