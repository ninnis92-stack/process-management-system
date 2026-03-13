#!/usr/bin/env python3
"""
Force-enable vibe/theme for admin@example.com and globally.
Run: python scripts/fix_admin_vibe.py
"""
from app import create_app, db
from app.models import User, FeatureFlags

ADMIN_EMAIL = "admin@example.com"

app = create_app()
with app.app_context():
    # Enable global vibe feature
    flags = FeatureFlags.get()
    flags.vibe_enabled = True
    db.session.commit()
    print("Global vibe_enabled set to True.")

    # Enable admin user vibe button and disable dark mode
    user = User.query.filter_by(email=ADMIN_EMAIL).first()
    if user:
        user.vibe_button_enabled = True
        user.dark_mode = False
        db.session.commit()
        print(f"User {ADMIN_EMAIL}: vibe_button_enabled=True, dark_mode=False.")
    else:
        print(f"User {ADMIN_EMAIL} not found.")
