"""Durable turn journal and prepared memory jobs, separate from canonical memory."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import Column, String, JSON, DateTime, MetaData, Table, select, update, inspect

metadata = MetaData()
turns = Table(
    "voice_turn_journal", metadata,
    Column("source_id", String(160), primary_key=True),
    Column("customer_id", String(80), nullable=True, index=True),
    Column("payload", JSON, nullable=False),
    Column("prepared", JSON, nullable=True),
    Column("status", String(24), nullable=False, index=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


class VoiceStore:
    def __init__(self, engine):
        self.engine = engine

    async def ready(self):
        exists = await asyncio.to_thread(lambda: inspect(self.engine).has_table(turns.name))
        if not exists:
            raise RuntimeError("Chưa có voice journal. Chạy python scripts/migrate_voice.py")

    async def save(self, source, customer_id, payload, *, status="pending"):
        def save():
            with self.engine.begin() as conn:
                row = conn.execute(select(turns.c.source_id).where(turns.c.source_id == source)).first()
                values = dict(customer_id=customer_id, payload=deepcopy(payload), status=status,
                              updated_at=datetime.now(timezone.utc))
                if row:
                    conn.execute(update(turns).where(turns.c.source_id == source).values(**values))
                else:
                    conn.execute(turns.insert().values(source_id=source, **values))
        await asyncio.to_thread(save)

    async def get(self, source):
        def get():
            with self.engine.connect() as conn:
                row = conn.execute(select(turns).where(turns.c.source_id == source)).mappings().first()
                return dict(row) if row else None
        return await asyncio.to_thread(get)

    async def save_snapshot(self, source, brief, memory):
        def write():
            with self.engine.begin() as conn:
                payload = conn.execute(select(turns.c.payload).where(turns.c.source_id == source)).scalar_one()
                payload = {**payload, "call_brief": brief, "memory_snapshot": memory,
                           "snapshot_at": datetime.now(timezone.utc).isoformat()}
                conn.execute(update(turns).where(turns.c.source_id == source).values(
                    payload=payload, updated_at=datetime.now(timezone.utc)))
        await asyncio.to_thread(write)

    async def prepared(self, source, batch):
        await self._update(source, prepared=batch, status="prepared")

    async def committed(self, source):
        await self._update(source, status="committed")

    async def _update(self, source, **values):
        def write():
            with self.engine.begin() as conn:
                conn.execute(update(turns).where(turns.c.source_id == source).values(
                    **values, updated_at=datetime.now(timezone.utc)))
        await asyncio.to_thread(write)

    async def pending(self):
        def read():
            with self.engine.connect() as conn:
                return [dict(r) for r in conn.execute(select(turns).where(
                    turns.c.status.in_(["pending", "prepared"])
                ).order_by(turns.c.updated_at)).mappings()]
        return await asyncio.to_thread(read)
