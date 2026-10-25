"""One in-process customer writer for both channels; replayable voice write batches."""
import asyncio
from contextlib import asynccontextmanager
from copy import copy, deepcopy
from telesale_agent.adapters.memory.in_memory import InMemoryCustomerMemoryRepository
from telesale_agent.adapters.memory.write_session import TurnMemoryWriteSession

_locks: dict[tuple[int, str], asyncio.Lock] = {}


@asynccontextmanager
async def customer_writer(customer_id):
    key = (id(asyncio.get_running_loop()), customer_id or "__anonymous__")
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        yield


async def persist_shared(services, context):
    if not services.persist:
        return []
    customer_id = context.identity.customer_id if context.identity else None
    async with customer_writer(customer_id):
        if services.customer_context:
            await services.customer_context.refresh_memory(context)
        return await services.persist.persist(context) or []


class RecordingRepository:
    """Run the existing persister once against RAM; journal its deterministic effects."""
    def __init__(self, snapshot, source):
        self.memory = InMemoryCustomerMemoryRepository(daily_files=True)
        self.memory.seed_snapshot(snapshot["customer_id"], snapshot)
        self.source = source
        self.operations = []

    def __getattr__(self, name):
        target = getattr(self.memory, name)
        if name not in {"upsert_fact", "record_atomic_fact", "record_episode", "record_foresight",
                        "update_profile", "update_behaviors"}:
            return target

        def record(customer, value, *args, **kwargs):
            arguments = [customer, value, *args]
            previous = None
            marker = ""
            if name == "upsert_fact":
                previous = self.memory.latest_fact(customer, value)
            elif name.startswith("record_"):
                marker = "[voice-source:" + self.source + ":" + str(len(self.operations)) + "]"
                arguments[1] = value + "\n" + marker
                if name == "record_episode":
                    kwargs["source_id"] = self.source
            result = target(*arguments, **kwargs)
            self.operations.append({"method": name, "args": arguments, "kwargs": kwargs,
                                    "previous": previous, "marker": marker})
            return result
        return record


async def commit_voice(services, context, store, source):
    """Prepared batch survives a crash between canonical writes and journal commit."""
    customer_id = context.identity.customer_id if context.identity else None
    if not customer_id or not services.persist:
        await store.committed(source)
        return []
    async with customer_writer(customer_id):
        job = await store.get(source)
        if job["status"] == "committed":
            return []
        if services.customer_context:
            await services.customer_context.refresh_memory(context)
        batch = job.get("prepared")
        if batch is None:
            snapshot = context.state.customer_memory or services.memory.load(customer_id)
            recorder = RecordingRepository(snapshot, source)
            persister = copy(services.persist)
            persister.memory = recorder
            draft = deepcopy(context)
            writes = await persister.persist(draft) or []
            batch = {"operations": recorder.operations, "writes": writes}
            await store.prepared(source, batch)
        session = TurnMemoryWriteSession(services.memory, context)
        repository = session.repository
        for operation in batch["operations"]:
            name, args = operation["method"], operation["args"]
            marker = operation.get("marker")
            if marker and marker in str(repository.load(customer_id)):
                continue
            if name == "upsert_fact":
                current = repository.latest_fact(customer_id, args[1])
                # A newer conversation may already have superseded this pending write.
                if current not in (operation["previous"], args[2]):
                    continue
            getattr(repository, name)(*args, **operation["kwargs"])
        await session.commit()
        await store.committed(source)
        context.state.memory_deltas.clear()
        context.state.customer_memory = repository.load(customer_id)
        return batch["writes"]
