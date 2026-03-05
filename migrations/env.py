from __future__ import with_statement
import sys
import os

from logging.con***REMOVED***g import ***REMOVED***leCon***REMOVED***g

from sqlalchemy import engine_from_con***REMOVED***g
from sqlalchemy import pool

# this is the Alembic Con***REMOVED***g object, which provides
# access to the values within the .ini ***REMOVED***le in use.
from alembic import context

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__***REMOVED***le__), '..')))

from app import create_app
from app.extensions import db

app = create_app()

# Interpret the con***REMOVED***g ***REMOVED***le for Python logging.
con***REMOVED***g = context.con***REMOVED***g
***REMOVED***leCon***REMOVED***g(con***REMOVED***g.con***REMOVED***g_***REMOVED***le_name)

# Set target metadata for 'autogenerate'
target_metadata = db.metadata


def run_migrations_offline():
    url = app.con***REMOVED***g.get('SQLALCHEMY_DATABASE_URI') or app.con***REMOVED***g.get('DATABASE_URL')
    context.con***REMOVED***gure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = db.engine

    with connectable.connect() as connection:
        context.con***REMOVED***gure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
