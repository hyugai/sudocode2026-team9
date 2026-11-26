"""Optional memory lifecycle operations shared by HTTP and realtime channels."""

async def flush_customer_memory(services, state):
    memory = getattr(services, "memory", None)
    flush = getattr(memory, "flush_customer", None)
    identity = getattr(state, "identity", None)
    if callable(flush) and identity and identity.customer_id:
        await flush(identity.customer_id)
