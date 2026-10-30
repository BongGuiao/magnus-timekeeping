import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import Integer
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, init_db_models
from app.filemaintenance.schedule.infrastructure.db_model import PositiveMinutes

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL must be set to run Alembic migrations.")
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

init_db_models()
target_metadata = Base.metadata
managed_schemas = {table.schema for table in target_metadata.tables.values()}


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in managed_schemas
    return True


def include_object(object_, name, type_, reflected, compare_to):
    return not (type_ == "index" and name == "uq_holidays_calendar_date_name_scope")


def compare_type(context_, inspected_column, metadata_column, inspected_type, metadata_type):
    if isinstance(metadata_type, PositiveMinutes) and isinstance(inspected_type, Integer):
        return False
    return None


def run_migrations_offline():
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        compare_type=compare_type,
        compare_server_default=True,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
