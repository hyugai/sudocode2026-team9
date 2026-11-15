"""Keep active customer snapshots in RAM and flush them on end/idle/shutdown."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from telesale_agent.application.memory.snapshot import empty_snapshot, render_snapshot, parse_snapshot

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    snapshot: dict[str, Any]
    baseline: dict[str, Any]
    changed_at: float
    version: int = 0
    saved_version: int = 0
    retry_at: float = 0


class BufferedCustomerMemoryStore:
    """Single-process write buffer; RAM is intentionally not crash durable."""

    def __init__(self, remote, *, idle_seconds: float = 120, poll_seconds: float = 5,
                 flush_timeout: float = 20, clock=time.monotonic):
        self.remote = remote
        self.idle_seconds = idle_seconds
        self.poll_seconds = poll_seconds
        self.flush_timeout = flush_timeout
        self.clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.RLock()
        self._customer_locks: dict[str, threading.Lock] = {}
        self._jobs: dict[str, asyncio.Task] = {}
        self._acknowledgements: dict[str, dict[str, tuple[int, Any]]] = {}
        self._worker: asyncio.Task | None = None
        self._upload_slots = asyncio.Semaphore(4)

    def _customer_lock(self, customer_id):
        with self._lock:
            return self._customer_locks.setdefault(customer_id, threading.Lock())

    def load(self, customer_id: str) -> dict[str, Any]:
        # Cold reads serialize only for this customer, never across the network
        # while holding the shared cache lock.
        with self._lock:
            entry = self._entries.get(customer_id)
            if entry:
                entry.changed_at = self.clock()
                return deepcopy(entry.snapshot)
        with self._customer_lock(customer_id):
            with self._lock:
                entry = self._entries.get(customer_id)
            if entry is None:
                snapshot = self.remote.load(customer_id)
                entry = _Entry(deepcopy(snapshot), deepcopy(snapshot), self.clock())
                # A new customer gets a visible tree even before learning facts.
                if snapshot == empty_snapshot(customer_id):
                    entry.version = 1
                with self._lock:
                    self._entries[customer_id] = entry
            with self._lock:
                entry.changed_at = self.clock()
                return deepcopy(entry.snapshot)

    def save_snapshot(self, customer_id, snapshot, *, previous_snapshot=None):
        # Validate and copy before publishing a RAM snapshot to other sessions.
        validated = parse_snapshot(render_snapshot(snapshot), customer_id)
        self.load(customer_id)
        with self._lock:
            entry = self._entries[customer_id]
            if entry.snapshot != validated:
                entry.snapshot = validated
                entry.version += 1
            entry.changed_at = self.clock()

    def pending_customers(self, *, idle_only=False):
        now = self.clock()
        with self._lock:
            return [key for key, entry in self._entries.items()
                    if (entry.version != entry.saved_version or self._acknowledgements.get(key))
                    and (not idle_only or (
                        now >= entry.retry_at if entry.retry_at else
                        now - entry.changed_at >= self.idle_seconds))]

    def _flush_once(self, customer_id):
        with self._customer_lock(customer_id):
            with self._lock:
                entry = self._entries.get(customer_id)
                if entry is None or entry.version == entry.saved_version:
                    return
                snapshot, baseline = deepcopy(entry.snapshot), deepcopy(entry.baseline)
                version = entry.version
            self.remote.save_snapshot(customer_id, snapshot, previous_snapshot=baseline)
            with self._lock:
                # Updates arriving during the upload keep their newer version
                # and stay pending for the next flush.
                entry.baseline = snapshot
                entry.saved_version = version
                entry.retry_at = 0

    def defer_commit(self, customer_id, source, acknowledge):
        """Keep voice journal jobs replayable until their RAM version is durable."""
        with self._lock:
            version = self._entries[customer_id].version
            self._acknowledgements.setdefault(customer_id, {})[source] = (version, acknowledge)

    async def _acknowledge_saved(self, customer_id):
        with self._lock:
            entry = self._entries.get(customer_id)
            if entry is None:
                return
            saved = entry.saved_version
            callbacks = [(source, item) for source, item in self._acknowledgements.get(customer_id, {}).items()
                         if item[0] <= saved]
        for source, item in callbacks:
            await item[1]()
            with self._lock:
                pending = self._acknowledgements.get(customer_id, {})
                if pending.get(source) is item:
                    pending.pop(source)

    async def _upload(self, customer_id):
        for attempt in range(3):
            try:
                async with self._upload_slots:
                    await asyncio.to_thread(self._flush_once, customer_id)
                    await self._acknowledge_saved(customer_id)
                with self._lock:
                    if customer_id in self._entries:
                        self._entries[customer_id].retry_at = 0
                return
            except Exception:
                if attempt == 2:
                    with self._lock:
                        self._entries[customer_id].retry_at = self.clock() + 15
                    raise
                await asyncio.sleep(2 ** attempt)

    def _job(self, customer_id):
        task = self._jobs.get(customer_id)
        if task is None:
            task = asyncio.create_task(self._upload(customer_id))
            self._jobs[customer_id] = task

            def finished(done):
                self._jobs.pop(customer_id, None)
                if not done.cancelled() and done.exception():
                    logger.error("Customer memory upload pending: %s", customer_id,
                                 exc_info=done.exception())
            task.add_done_callback(finished)
        return task

    async def flush_customer(self, customer_id):
        with self._lock:
            cached = customer_id in self._entries
        if customer_id and cached:
            # A timed-out caller must not cancel an upload thread and start a
            # competing write. The same tracked job is reused by later retries.
            await asyncio.wait_for(asyncio.shield(self._job(customer_id)), self.flush_timeout)

    async def flush_idle(self):
        results = await asyncio.gather(
            *(self.flush_customer(key) for key in self.pending_customers(idle_only=True)),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Idle memory flush will retry: %s", result)

    async def _run(self):
        while True:
            await asyncio.sleep(self.poll_seconds)
            await self.flush_idle()
            with self._lock:
                for key, entry in list(self._entries.items()):
                    if (entry.version == entry.saved_version and not self._acknowledgements.get(key)
                            and key not in self._jobs
                            and self.clock() - entry.changed_at >= self.idle_seconds):
                        del self._entries[key]

    async def start(self):
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    async def close(self):
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None
        results = await asyncio.gather(
            *(self.flush_customer(key) for key in self.pending_customers()),
            return_exceptions=True,
        )
        if any(isinstance(result, Exception) for result in results):
            logger.error("Shutdown finished with unsynced customer memory: %s", self.pending_customers())

    def search_archive(self, customer_id, query, *, section="episodes", day=None):
        # Existing archive searches must see newer RAM detail too.
        current = self.load(customer_id)
        if section in {"user", "behaviors", "facts"}:
            if day:
                raise ValueError("A static archive section has no day")
            content = self.remote._individual_files(current)[f"{section}.md"]
            return {"section": section, "hits": [{"source": f"{section}.md", "content": content[:1200]}] if content else []}
        if day:
            prefix = {"episodes": "episode", "atomic_facts": "fact", "foresights": "foresight"}.get(section)
            if prefix is None:
                raise ValueError("Unsupported memory archive section")
            for item in current.get(section, []):
                if item.get("source") == f"{prefix}-{day}.md":
                    return {"section": section, "hits": [{"source": day, "content": item["content"][:1200]}]}
        result = self.remote.search_archive(customer_id, query, section=section, day=day)
        if not day:
            import re
            terms = [term for term in re.findall(r"\w+", query.casefold()) if len(term) >= 3]
            live = [{"source": f"{section}/{item['source']}", "content": item.get("content", "")[:900],
                     "score": sum(term in item.get("content", "").casefold() for term in terms)}
                    for item in current.get(section, [])]
            sources = {item["source"] for item in live}
            combined = live + [item for item in result["hits"] if item["source"] not in sources]
            result["hits"] = sorted(combined, key=lambda item: item.get("score", 0), reverse=True)[:3]
        return result
