from app import create_app
from app.extensions import db
from app.models import Noti***REMOVED***cation, User

app = create_app()
with app.app_context():
    print('DB URI:', app.con***REMOVED***g['SQLALCHEMY_DATABASE_URI'])
    print('Users:', User.query.count())
    print('Noti***REMOVED***cations:', Noti***REMOVED***cation.query.count())
    for n in Noti***REMOVED***cation.query.limit(10).all():
        print(n.id, n.user_id, n.title, n.is_read, n.created_at)
