from werkzeug.security import generate_password_hash
from app import create_app
from app.extensions import db
from app.models import User
from sqlalchemy import inspect, text

def main():
    app = create_app()
    with app.app_context():
        # Ensure DB schema includes `is_admin` before running ORM queries.
        try:
            # Prefer the new `db.engine` when available, else fall back to get_engine
            engine = getattr(db, "engine", None) or db.get_engine(app)
            inspector = inspect(engine)
            cols = [c.get("name") for c in inspector.get_columns("user")]
            if "is_admin" not in cols:
                try:
                    # Use a connection and SQLAlchemy `text()` to execute safely across
                    # SQLAlchemy versions. Use INTEGER DEFAULT 0 which is compatible
                    # with SQLite.
                    with engine.connect() as conn:
                        conn.execute(text("ALTER TABLE user ADD COLUMN is_admin INTEGER DEFAULT 0"))
                        # Some DB/APIs require an explicit commit for DDL
                        try:
                            conn.commit()
                        except Exception:
                            pass
                except Exception:
                    # Best-effort; if ALTER fails (e.g., complex schema), continue and
                    # let later commit-time handling attempt again.
                    pass
        except Exception:
            # If inspection isn't available, proceed — seed has additional
            # fallback handling later when commits fail.
            pass
        # Create nine demo users for testing. Keep the first three as
        # the original Dept A/B/C users so existing tests and examples
        # continue to work. Additional users allow exercising different
        # department views during manual testing; admin roles can be
        # granted via `ADMIN_EMAILS` in config (SSO will set roles later).
        demo = [
            ("Dept A User", "a@example.com", "A"),
            ("Dept B User", "b@example.com", "B"),
            ("Dept C User", "c@example.com", "C"),
            ("Dept A User 2", "a2@example.com", "A"),
            ("Dept B User 2", "b2@example.com", "B"),
            ("Dept C User 2", "c2@example.com", "C"),
            ("Dept A User 3", "a3@example.com", "A"),
            ("Dept B User 3", "b3@example.com", "B"),
            ("Dept C User 3", "c3@example.com", "C"),
        ]
        for idx, (name, email, dept) in enumerate(demo):
            # Keep the first three users active by default for convenience.
            # The remaining demo accounts are created deactivated so admins
            # can exercise activation/role assignment in the admin UI (and
            # SSO will set proper roles later).
            active = True if idx < 3 else False
            u = User.query.filter_by(email=email).first()
            if not u:
                u = User(
                    name=name,
                    email=email,
                    department=dept,
                    password_hash=generate_password_hash("password123", method="pbkdf2:sha256"),
                    is_active=active,
                )
                db.session.add(u)
        db.session.commit()

        # Ensure admin user(s) exist. Prefer ADMIN_EMAILS from config; else create a default admin.
        admin_emails = app.config.get("ADMIN_EMAILS") or []
        if not admin_emails:
            admin_emails = ["admin@example.com"]

        for aemail in admin_emails:
            aemail = aemail.strip().lower()
            if not aemail:
                continue
            u = User.query.filter_by(email=aemail).first()
            if not u:
                u = User(
                    name="Admin",
                    email=aemail,
                    department="A",
                    password_hash=generate_password_hash("admin123", method="pbkdf2:sha256"),
                    is_active=True,
                )
                try:
                    # Try to set is_admin flag (may require DB column present)
                    u.is_admin = True
                except Exception:
                    pass
                db.session.add(u)
            else:
                try:
                    u.is_admin = True
                except Exception:
                    pass
        try:
            db.session.commit()
        except Exception:
            # If the DB schema doesn't yet include `is_admin`, attempt to add the column (dev-only)
            try:
                db.session.rollback()
                engine = db.get_engine(app)
                # Best-effort ALTER TABLE to add is_admin column for SQLite/Postgres
                engine.execute("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0")
            except Exception:
                pass
            # Try commit again (users should exist even if is_admin couldn't be set)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        print("DB =", ...)
        print("Seeded users:")
        print("a@example.com / password123 (Dept A)")
        print("b@example.com / password123 (Dept B)")
        print("c@example.com / password123 (Dept C)")
        print("Admin account(s):")
        for e in admin_emails:
            print(f"{e} / admin123")

if __name__ == "__main__":
    main()