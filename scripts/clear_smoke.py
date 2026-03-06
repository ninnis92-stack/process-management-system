#!/usr/bin/env python3
"""Clear smoke-created Request rows (title LIKE 'SMOKE_%').

Run inside the production container via `flyctl ssh console --command "python3 scripts/clear_smoke.py"`.
"""
from app import create_app
from app.extensions import db
from app.models import Request as R

def main():
    app = create_app()
    with app.app_context():
        cnt = R.query.filter(R.title.like('SMOKE_%')).delete(synchronize_session=False)
        db.session.commit()
        print('deleted', cnt)

if __name__ == '__main__':
    main()
