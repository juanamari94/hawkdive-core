import os
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

from hawkdive.database import database_url
from hawkdive.tables import Base

path = Path(os.getenv('HAWKDIVE_DB_PATH', 'hawkdive.sqlite3'))

if context.is_offline_mode():
    context.configure(url=database_url(path, asynchronous=False), target_metadata=Base.metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url(path, asynchronous=False), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
