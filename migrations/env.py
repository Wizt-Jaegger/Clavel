"""Run explicit PostgreSQL migrations using the application's secret settings."""

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from clavel.core.settings import load_settings
from clavel.database.inventory import metadata


def run_migrations() -> None:
    settings = load_settings()
    url = make_url(settings.database_url.get_secret_value()).set(
        drivername="postgresql+psycopg",
    )
    if context.is_offline_mode():
        context.configure(
            url=url, target_metadata=metadata, literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(
        url, poolclass=pool.NullPool,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=30000"},
    )
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
