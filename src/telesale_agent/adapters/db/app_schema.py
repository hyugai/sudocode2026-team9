"""Add the five application tables without altering existing business data."""

import os

from dotenv import load_dotenv
from sqlalchemy import CheckConstraint, UniqueConstraint, create_engine, inspect
from sqlalchemy.engine import Engine

from .app_models import APP_TABLES
from .models import Base


def create_app_engine(database_url: str | None = None) -> Engine:
    """No global engine or connection on import; DATABASE_URL takes priority."""
    load_dotenv()
    url = database_url or os.environ.get("DATABASE_URL") or os.environ.get("DB_URL")
    if not url:
        raise ValueError("Chưa cấu hình DATABASE_URL (hoặc DB_URL).")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, pool_pre_ping=True, pool_recycle=300,
                         hide_parameters=True, connect_args={"connect_timeout": 10})


def migrate_app_data(engine: Engine) -> list[str]:
    """Create missing tables/indexes. Refuse incompatible pre-existing tables."""
    if engine.dialect.name != "postgresql":
        raise ValueError("Migration này yêu cầu PostgreSQL.")
    schema = engine.get_execution_options().get("schema_translate_map", {}).get(None)
    with engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table("customers", schema=schema):
            raise ValueError("Chưa có bảng customers. Thiết lập schema CRM trước; migration này không tạo/reset CRM.")
        for table in APP_TABLES:
            if inspector.has_table(table.name, schema=schema):
                actual = {column["name"]: column for column in inspector.get_columns(table.name, schema=schema)}
                columns_match = all(
                    column.name in actual
                    and str(column.type.compile(dialect=engine.dialect)) == str(actual[column.name]["type"].compile(dialect=engine.dialect))
                    and column.nullable == actual[column.name]["nullable"]
                    for column in table.columns
                )
                primary_key = set(inspector.get_pk_constraint(table.name, schema=schema)["constrained_columns"])
                unique_keys = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name, schema=schema)}
                checks = {item["name"] for item in inspector.get_check_constraints(table.name, schema=schema)}
                foreign_keys = {
                    (tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]), item["options"].get("ondelete"))
                    for item in inspector.get_foreign_keys(table.name, schema=schema)
                }
                constraints_match = all(
                    tuple(column.name for column in constraint.columns) in unique_keys
                    for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
                ) and all(
                    constraint.name in checks
                    for constraint in table.constraints if isinstance(constraint, CheckConstraint)
                ) and all(
                    (tuple(constraint.column_keys), constraint.referred_table.name,
                     tuple(element.column.name for element in constraint.elements), constraint.ondelete) in foreign_keys
                    for constraint in table.foreign_key_constraints
                )
                if not columns_match or primary_key != set(table.primary_key.columns.keys()) or not constraints_match:
                    raise ValueError(f"Bảng {table.name} có schema không tương thích; cần migration riêng.")
        Base.metadata.create_all(connection, tables=APP_TABLES, checkfirst=True)
        for table in APP_TABLES:
            for index in table.indexes:
                index.create(connection, checkfirst=True)
    return [table.name for table in APP_TABLES]
