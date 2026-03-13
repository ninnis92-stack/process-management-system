#!/usr/bin/env python3
"""
Create admin@example.com with password admin123 and enable vibe/theme settings.
Run: python scripts/create_admin_with_vibe.py
"""
from app import create_app, db
from app.models import User, FeatureFlags
from werkzeug.security import generate_password_hash

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin123"

app = create_app()
with app.app_context():
    # Create user if not exists
    user = User.query.filter_by(email=ADMIN_EMAIL).first()
    if not user:
        user = User(
            email=ADMIN_EMAIL,
            name="Admin User",
            department="A",
            password_hash=generate_password_hash(ADMIN_PASSWORD, method="pbkdf2:sha256"),
            is_active=True,
            is_admin=True,
            vibe_button_enabled=True,
            dark_mode=False,
        )
        db.session.add(user)
        db.session.commit()
        print(f"Created admin user {ADMIN_EMAIL}.")
    else:
        print(f"User {ADMIN_EMAIL} already exists.")
    # Enable global vibe
    flags = FeatureFlags.get()
    flags.vibe_enabled = True
    db.session.commit()
    print("Global vibe_enabled set to True.")
    # Ensure user settings
    user.vibe_button_enabled = True
    user.dark_mode = False
    db.session.commit()
    print(f"User {ADMIN_EMAIL}: vibe_button_enabled=True, dark_mode=False.")
