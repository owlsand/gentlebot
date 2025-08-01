import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool, text

from alembic import context
import logging

# log Alembic messages at INFO level
logging.getLogger('alembic').setLevel(logging.INFO)
# optionally, see full SQLAlchemy engine debugging
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
url = os.getenv("PG_DSN") or os.getenv("DATABASE_URL")
if not url:
    user = os.getenv("PG_USER")
    pwd = os.getenv("PG_PASSWORD")
    db = os.getenv("PG_DB")
    if user and pwd and db:
        url = f"postgresql+asyncpg://{user}:{pwd}@db:5432/{db}"
if url:
    config.set_main_option("sqlalchemy.url", url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    section = config.get_section(config.config_ini_section, {}).copy()
    url = section.get("sqlalchemy.url")
    if url and url.startswith("postgresql+asyncpg://"):
        section["sqlalchemy.url"] = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        echo=True
    )

    with connectable.connect() as connection:
        connection.execute(text("SET search_path=discord,public"))
        connection.commit()
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            version_table_schema="discord",  
            include_schemas=True,
            compare_type=True,
            compare_server_default=True
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
