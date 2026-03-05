#!/usr/bin/env python3
"""Utility to create DB tables on a deployed instance.

Run this from the deployed container (e.g. `python3 /app/scripts/remote_create_tables.py`).
"""
import sys
import os

sys.path.append('/app')

from app import create_app
from app.extensions import db

def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        print('created_tables')

if __name__ == '__main__':
    main()
