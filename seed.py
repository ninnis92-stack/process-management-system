from werkzeug.security import generate_password_hash
from app import create_app
from app.extensions import db
from app.models import FeatureFlags, SiteConfig, User
from sqlalchemy import inspect, text
import json


def main():
    app = create_app()
    with app.app_context():
        # Ensure DB schema includes `is_admin` before running ORM queries.
        try:
            # Prefer the new `db.engine` when available, else fall back to get_engine
            engine = getattr(db, "engine", None) or db.get_engine(app)
            inspector = inspect(engine)
            cols = [c.get("name") for c in inspector.get_columns("user")]
            # Ensure columns added by recent migrations exist so ORM queries
            # that reference them don't fail when seed runs on deployed DBs.
            if "dark_mode" not in cols:
                try:
                    with engine.connect() as conn:
                        conn.execute(text("ALTER TABLE \"user\" ADD COLUMN dark_mode BOOLEAN DEFAULT FALSE"))
                        try:
                            conn.commit()
                        except Exception:
                            pass
                except Exception:
                    pass

            if "is_admin" not in cols:
                try:
                    # Use a connection and SQLAlchemy `text()` to execute safely across
                    # SQLAlchemy versions. Use INTEGER DEFAULT 0 which is compatible
                    # with SQLite.
                    with engine.connect() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE user ADD COLUMN is_admin INTEGER DEFAULT 0"
                            )
                        )
                        # Some DB/APIs require an explicit commit for DDL
                        try:
                            conn.commit()
                        except Exception:
                            pass
                except Exception:
                    # Best-effort; if ALTER fails (e.g., complex schema), continue and
                    # let later commit-time handling attempt again.
                    pass
            if "quote_interval" not in cols:
                try:
                    # add column used by rolling quote feature
                    with engine.connect() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE user ADD COLUMN quote_interval INTEGER"
                            )
                        )
                        try:
                            conn.commit()
                        except Exception:
                            pass
                except Exception:
                    pass
            if "daily_nudge_limit" not in cols:
                try:
                    with engine.connect() as conn:
                        conn.execute(
                            text(
                                "ALTER TABLE user ADD COLUMN daily_nudge_limit INTEGER NOT NULL DEFAULT 1"
                            )
                        )
                        try:
                            conn.commit()
                        except Exception:
                            pass
                except Exception:
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
                    password_hash=generate_password_hash(
                        "password123", method="pbkdf2:sha256"
                    ),
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
                    password_hash=generate_password_hash(
                        "admin123", method="pbkdf2:sha256"
                    ),
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

        # backfill any missing daily_nudge_limit values (new column may be NULL)
        try:
            for u in User.query.all():
                if getattr(u, "daily_nudge_limit", None) is None:
                    u.daily_nudge_limit = 1
            db.session.commit()
        except Exception:
            db.session.rollback()
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

        flags = FeatureFlags.get()
        for attr, default in (
            ("enable_notifications", True),
            ("enable_nudges", True),
            ("allow_user_nudges", False),
            ("vibe_enabled", True),
            ("sso_admin_sync_enabled", True),
            ("sso_department_sync_enabled", False),
            ("enable_external_forms", False),
            ("rolling_quotes_enabled", True),
        ):
            if getattr(flags, attr, None) is None:
                setattr(flags, attr, default)
        db.session.add(flags)

        cfg = SiteConfig.get()
        normalized_sets = SiteConfig.normalize_quote_sets(getattr(cfg, "rolling_quote_sets", None))
        # ensure each set has at least 30 entries so the rolling quote feature
        # can cycle without immediately repeating.  We simply repeat existing
        # quotes in a round-robin fashion if a set is too small.
        for name, quotes in normalized_sets.items():
            if isinstance(quotes, list) and len(quotes) < 30:
                if not quotes:
                    quotes.extend([f"Quote {i+1}" for i in range(30)])
                else:
                    i = 0
                    while len(quotes) < 30:
                        quotes.append(quotes[i % len(quotes)])
                        i += 1
        cfg._rolling_quote_sets = json.dumps(normalized_sets)
        if not getattr(cfg, "active_quote_set", None) or cfg.active_quote_set not in normalized_sets:
            cfg.active_quote_set = "default"
        # normalize any existing user preferences just in case there are stray
        # upper‑case or whitespace‑padded values from earlier releases or manual
        # edits; the model's validator will also keep future writes consistent.
        try:
            from sqlalchemy import func

            db.session.query(User).filter(User.quote_set.isnot(None)).update(
                {User.quote_set: func.lower(User.quote_set)}, synchronize_session=False
            )
        except Exception:
            pass
        db.session.commit()
        print("DB =", ...)
        print("Seeded users:")
        print("a@example.com / password123 (Dept A)")
        print("b@example.com / password123 (Dept B)")
        print("c@example.com / password123 (Dept C)")
        print("Admin account(s):")
        for e in admin_emails:
            print(f"{e} / admin123")
        print("Feature flags:")
        print(f"vibe_enabled: {bool(getattr(flags, 'vibe_enabled', True))}")
        print("Quote sets:")
        for name, quotes in normalized_sets.items():
            print(f"{name}: {len(quotes)} quote(s)")


if __name__ == "__main__":
    main()
