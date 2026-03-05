from __future__ import with_statement
import sys
import os

from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
from alembic import context

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db

app = create_app()

# Interpret the config file for Python logging.
config = context.config
fileConfig(config.config_file_name)

# Set target metadata for 'autogenerate'
target_metadata = db.metadata


def run_migrations_offline():
    url = app.config.get('SQLALCHEMY_DATABASE_URI') or app.config.get('DATABASE_URL')
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = db.engine

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
