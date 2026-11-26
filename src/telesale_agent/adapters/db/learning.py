"""Durable learning inbox. Callers own redaction and application transactions."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, MetaData, String, Table,
    UniqueConstraint, inspect, select, update,
)

metadata = MetaData()


class LearningSnapshotTooLarge(ValueError):
    """The complete session cannot fit the configured learning input contract."""


sessions = Table(
    "learning_sessions", metadata,
    Column("id", String(64), primary_key=True),
    Column("channel", String(16), nullable=False),
    Column("conversation_id", String(160), nullable=False),
    Column("status", String(16), nullable=False),
    Column("context", JSON, nullable=False),
    Column("checkpoint", JSON),
    Column("lessons", JSON),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("channel", "conversation_id", name="uq_learning_session"),
    CheckConstraint("status IN ('active', 'finalizing', 'ended')", name="ck_learning_session_status"),
)
turns = Table(
    "learning_turns", metadata,
    Column("session_id", String(64), ForeignKey("learning_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("turn_number", Integer, primary_key=True),
    Column("payload", JSON, nullable=False),
)
jobs = Table(
    "learning_jobs", metadata,
    Column("id", String(64), primary_key=True),
    Column("session_id", String(64), ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("workflow_version", Integer, nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("status", String(16), nullable=False, index=True),
    Column("attempts", Integer, nullable=False),
    Column("retry_at", DateTime(timezone=True), nullable=False),
    Column("error", String(100)),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("session_id", "revision", "workflow_version", name="uq_learning_job_revision"),
    CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name="ck_learning_job_status"),
)


def now():
    return datetime.now(timezone.utc)


def session_key(channel, conversation_id):
    return hashlib.sha256(json.dumps([channel, conversation_id]).encode()).hexdigest()


class LearningRepository:
    """Synchronous operations; API/worker offload them with asyncio.to_thread.

    Account hooks pass their existing connection so history and learning commit
    together. A single backend process owns the session and worker lifecycle.
    """
    def __init__(self, engine):
        self.engine = engine

    def ready(self):
        with self.engine.connect() as connection:
            inspector = inspect(connection)
            schema = self.engine.get_execution_options().get("schema_translate_map", {}).get(None)
            if any(not inspector.has_table(t.name, schema=schema) for t in metadata.sorted_tables):
                raise RuntimeError("Chạy python scripts/migrate_learning.py trước khi bật self-learning")
            validate_schema(connection, schema)

    def get_session(self, key, connection=None):
        if connection is None:
            with self.engine.connect() as connection:
                return self.get_session(key, connection)
        row = connection.execute(select(sessions).where(sessions.c.id == key)).mappings().first()
        return dict(row) if row else None

    def ensure(self, connection, channel, conversation_id, context):
        key = session_key(channel, conversation_id)
        if self.get_session(key, connection) is None:
            connection.execute(sessions.insert().values(
                id=key, channel=channel, conversation_id=conversation_id, status="active",
                context=context, updated_at=now()))
        return key

    def save_turn(self, connection, channel, conversation_id, number, payload, context, checkpoint=None):
        key = self.ensure(connection, channel, conversation_id, context)
        row = self.get_session(key, connection)
        if row["status"] == "ended":
            raise ValueError("Phiên đã kết thúc. Hãy bắt đầu phiên mới.")
        previous = connection.execute(select(turns.c.payload).where(
            turns.c.session_id == key, turns.c.turn_number == number)).scalar_one_or_none()
        if previous is None:
            connection.execute(turns.insert().values(session_id=key, turn_number=number, payload=payload))
        elif previous != payload:
            raise ValueError("Learning turn conflicts with durable evidence")
        connection.execute(update(sessions).where(sessions.c.id == key).values(
            context=context, checkpoint=checkpoint, updated_at=now()))

    def read_turns(self, connection, key):
        return list(connection.execute(select(turns.c.payload).where(
            turns.c.session_id == key).order_by(turns.c.turn_number)).scalars())

    def queue(self, connection, key, snapshot, job_id):
        existing = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
        if existing:
            return dict(existing)
        # A terminal session always returns its original job, even if late
        # feedback or a retried end request has a different payload.
        existing = connection.execute(select(jobs).where(jobs.c.session_id == key)).mappings().first()
        if existing and self.get_session(key, connection)["status"] == "ended":
            return dict(existing)
        stamp = now()
        values = dict(id=job_id, session_id=key, revision=snapshot["revision"],
                      workflow_version=snapshot["workflow_version"], snapshot=snapshot,
                      status="queued", attempts=0, retry_at=stamp, error=None, updated_at=stamp)
        connection.execute(jobs.insert().values(**values))
        connection.execute(update(sessions).where(sessions.c.id == key).values(
            status="ended", checkpoint=None, updated_at=stamp))
        return values

    def freeze_lessons(self, key, lessons):
        with self.engine.begin() as connection:
            connection.execute(update(sessions).where(
                sessions.c.id == key, sessions.c.lessons.is_(None)).values(lessons=lessons))
            return self.get_session(key, connection)["lessons"]

    def recover_jobs(self):
        with self.engine.begin() as connection:
            connection.execute(update(jobs).where(jobs.c.status == "running").values(
                status="queued", attempts=jobs.c.attempts - 1, retry_at=now(), updated_at=now()))

    def claim(self, max_attempts):
        with self.engine.begin() as connection:
            query = select(jobs).where(jobs.c.status == "queued", jobs.c.attempts < max_attempts,
                                       jobs.c.retry_at <= now()).order_by(jobs.c.retry_at).limit(1)
            if self.engine.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = connection.execute(query).mappings().first()
            if not row:
                return None
            result = dict(row)
            result.update(status="running", attempts=row["attempts"] + 1)
            connection.execute(update(jobs).where(jobs.c.id == row["id"]).values(
                status="running", attempts=result["attempts"], updated_at=now()))
            return result

    def finish(self, job, error, max_attempts):
        status = "done" if error is None else "failed" if job["attempts"] >= max_attempts else "queued"
        delay = (5, 30)[min(max(job["attempts"] - 1, 0), 1)] if error else 0
        with self.engine.begin() as connection:
            connection.execute(update(jobs).where(jobs.c.id == job["id"]).values(
                status=status, error=error, retry_at=now() + timedelta(seconds=delay), updated_at=now()))

    def get_job(self, job_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
            return dict(row) if row else None


def migrate_learning(engine):
    """Add learning tables only. Never alter application/business data."""
    with engine.begin() as connection:
        schema = engine.get_execution_options().get("schema_translate_map", {}).get(None)
        validate_schema(connection, schema)
        metadata.create_all(connection, checkfirst=True)
        for table in metadata.sorted_tables:
            for index in table.indexes:
                index.create(connection, checkfirst=True)
    return [table.name for table in metadata.sorted_tables]


def validate_schema(connection, schema):
    """Refuse incompatible existing tables; migrations never silently reset data."""
    inspector = inspect(connection)
    for table in metadata.sorted_tables:
        if not inspector.has_table(table.name, schema=schema):
            continue
        actual = {column["name"]: column for column in inspector.get_columns(table.name, schema=schema)}
        compatible = all(
            column.name in actual and column.nullable == actual[column.name]["nullable"]
            and str(column.type.compile(dialect=connection.dialect)) == str(
                actual[column.name]["type"].compile(dialect=connection.dialect))
            for column in table.columns)
        primary = set(inspector.get_pk_constraint(table.name, schema=schema)["constrained_columns"])
        unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name, schema=schema)}
        checks = {item["name"] for item in inspector.get_check_constraints(table.name, schema=schema)}
        foreign = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]),
                    item["options"].get("ondelete"))
                   for item in inspector.get_foreign_keys(table.name, schema=schema)}
        compatible = compatible and all(
            tuple(column.name for column in constraint.columns) in unique
            for constraint in table.constraints if isinstance(constraint, UniqueConstraint))
        compatible = compatible and all(
            constraint.name in checks for constraint in table.constraints if isinstance(constraint, CheckConstraint))
        compatible = compatible and all(
            (tuple(constraint.column_keys), constraint.referred_table.name,
             tuple(item.column.name for item in constraint.elements), constraint.ondelete) in foreign
            for constraint in table.foreign_key_constraints)
        if not compatible or primary != set(table.primary_key.columns.keys()):
            raise ValueError(f"Bảng {table.name} không tương thích; cần migration riêng, không reset dữ liệu.")
