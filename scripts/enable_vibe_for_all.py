#!/usr/bin/env python3
"""
Enable vibe/theme for all users and globally.
Run: python scripts/enable_vibe_for_all.py
"""
from app import create_app, db
from app.models import User, FeatureFlags

app = create_app()
with app.app_context():
    # Enable global vibe feature
    flags = FeatureFlags.get()
    flags.vibe_enabled = True
    db.session.commit()
    print("Global vibe_enabled set to True.")

    # Enable vibe for all users and disable dark mode
    users = User.query.all()
    for user in users:
        user.vibe_button_enabled = True
        user.dark_mode = False
    db.session.commit()
    print(f"Enabled vibe_button and disabled dark_mode for {len(users)} users.")
