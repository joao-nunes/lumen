from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import lumen.auth.models  # noqa: F401  (registers auth tables on Base.metadata)
from lumen.config import get_settings
from lumen.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# An explicit URL (e.g. set by the test suite) takes precedence over settings.
if not config.get_main_option("sqlalchemy.url"):
    # Migrations run as the owner; runtime roles can't (and shouldn't) alter the schema.
    config.set_main_option("sqlalchemy.url", get_settings().admin_database_url)

target_metadata = Base.metadata

# Schemas owned by this application; everything else in the database is ignored.
MANAGED_SCHEMAS = {"public", "auth"}


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    if type_ == "schema":
        return name is None or name in MANAGED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_schemas=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
