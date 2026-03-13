#!/usr/bin/env python3
"""
Deploy: Always enable user theme/vibe controls for all users, regardless of global flag.
Run: python scripts/deploy_always_enable_user_vibe.py
"""
from app import create_app, db
from app.models import User

app = create_app()
with app.app_context():
    users = User.query.all()
    for user in users:
        user.vibe_button_enabled = True
        # Do not force dark_mode off, let users control it
    db.session.commit()
    print(f"Ensured vibe_button_enabled=True for {len(users)} users. User controls are now always available.")
