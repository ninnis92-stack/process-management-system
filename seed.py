from werkzeug.security import generate_password_hash
from app import create_app
from app.extensions import db
from app.models import User

def main():
    app = create_app()
    with app.app_context():
        demo = [
            ("Dept A User", "a@example.com", "A"),
            ("Dept B User", "b@example.com", "B"),
            ("Dept C User", "c@example.com", "C"),
        ]
        for name, email, dept in demo:
            u = User.query.***REMOVED***lter_by(email=email).***REMOVED***rst()
            if not u:
                u = User(
                    name=name,
                    email=email,
                    department=dept,
                    password_hash=generate_password_hash("password123", method="pbkdf2:sha256"),
                    is_active=True,
                )
                db.session.add(u)
        db.session.commit()
        print("DB =", ...)
        print("Seeded users:")
        print("a@example.com / password123 (Dept A)")
        print("b@example.com / password123 (Dept B)")
        print("c@example.com / password123 (Dept C)")

if __name__ == "__main__":
    main()