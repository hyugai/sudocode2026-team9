import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from test_object_storage_memory_snapshot import FakeS3, make_context
from telesale_agent.adapters.memory.buffered import BufferedCustomerMemoryStore
from telesale_agent.adapters.memory.object_storage import ObjectStorageCustomerMemoryRepository
from telesale_agent.adapters.memory.turn_persist import TurnMemoryPersister
from telesale_agent.application.memory.snapshot import empty_snapshot
from telesale_agent.core.models import ConversationState, CustomerIdentity


def setup_store(**kwargs):
    client = FakeS3()
    remote = ObjectStorageCustomerMemoryRepository(bucket="private", prefix="users", client=client)
    now = [0.0]
    store = BufferedCustomerMemoryStore(remote, clock=lambda: now[0], **kwargs)
    return client, remote, store, now


@pytest.mark.asyncio
async def test_turns_stay_in_ram_then_idle_exports_latest_memory():
    client, remote, store, now = setup_store()
    for size in (39, 40):
        context = make_context(store.load("C001"), deltas={"size": size})
        await TurnMemoryPersister(store).persist(context)
    assert client.put_count == 0
    assert client.get_count == 2  # Cold read only, including legacy lookup.
    now[0] = 119
    await store.flush_idle()
    assert client.put_count == 0
    now[0] = 120
    await store.flush_idle()
    assert remote.load("C001")["facts"] == {"size": 40}
    assert b"size: 40" in client.objects[("private", "users/C001/facts.md")]
    assert store.pending_customers() == []
    count = client.put_count
    await store.flush_idle()
    assert client.put_count == count


@pytest.mark.asyncio
async def test_flush_updates_all_learning_layers_and_preserves_older_days():
    client, remote, store, _ = setup_store()
    snapshot = store.load("C001")
    snapshot["facts"] = {"size": 39}
    for section, stem in (("atomic_facts", "fact"), ("episodes", "episode"), ("foresights", "foresight")):
        snapshot[section] = [{"source": f"{stem}-2026-10-{day:02d}.md", "content": f"day {day}"}
                             for day in (1, 2, 3)]
    store.save_snapshot("C001", snapshot)
    await store.flush_customer("C001")
    assert len(remote.load("C001")["episodes"]) == 2
    assert remote.load_archive("C001", "episodes", "2026-10-01") == "day 1"
    updated = store.load("C001")
    for section in ("atomic_facts", "episodes", "foresights"):
        updated[section][-1]["content"] += " latest"
    store.save_snapshot("C001", updated)
    await store.flush_customer("C001")
    for section, stem in (("atomic_facts", "fact"), ("episodes", "episode"), ("foresights", "foresight")):
        assert client.objects[("private", f"users/C001/{section}/{stem}-2026-10-03.md")] == b"day 3 latest"
    assert remote.load_archive("C001", "episodes", "2026-10-01") == "day 1"


@pytest.mark.asyncio
async def test_failure_keeps_pending_data_and_idle_retries(monkeypatch):
    client, remote, store, now = setup_store()
    snapshot = store.load("C001")
    snapshot["facts"]["size"] = 39
    store.save_snapshot("C001", snapshot)
    client.fail_put = True
    monkeypatch.setattr("telesale_agent.adapters.memory.buffered.asyncio.sleep", AsyncMock())
    with pytest.raises(RuntimeError, match="upload failed"):
        await store.flush_customer("C001")
    assert client.put_count == 3
    assert store.pending_customers() == ["C001"]
    assert store.load("C001")["facts"] == {"size": 39}
    client.fail_put = False
    now[0] = 15
    await store.flush_idle()
    assert remote.load("C001")["facts"] == {"size": 39}
    assert store.pending_customers() == []


@pytest.mark.asyncio
async def test_new_message_during_upload_remains_pending():
    _, remote, store, _ = setup_store()
    snapshot = store.load("C001")
    snapshot["facts"]["size"] = 39
    store.save_snapshot("C001", snapshot)
    entered, release = threading.Event(), threading.Event()
    save = remote.save_snapshot

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        save(*args, **kwargs)
    remote.save_snapshot = blocked
    task = asyncio.create_task(store.flush_customer("C001"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        latest = deepcopy(snapshot)
        latest["facts"]["size"] = 40
        store.save_snapshot("C001", latest)
    finally:
        release.set()
        await task
    assert remote.load("C001")["facts"]["size"] == 39
    assert store.load("C001")["facts"]["size"] == 40
    assert store.pending_customers() == ["C001"]
    await store.flush_customer("C001")
    assert remote.load("C001")["facts"]["size"] == 40


@pytest.mark.asyncio
async def test_timeout_reuses_running_upload_instead_of_competing_write():
    _, remote, store, _ = setup_store(flush_timeout=.01)
    store.load("C001")
    entered, release = threading.Event(), threading.Event()
    save = remote.save_snapshot
    calls = []

    def blocked(*args, **kwargs):
        calls.append(args[0])
        entered.set()
        assert release.wait(5)
        save(*args, **kwargs)
    remote.save_snapshot = blocked
    try:
        with pytest.raises(TimeoutError):
            await store.flush_customer("C001")
        assert entered.is_set()
        with pytest.raises(TimeoutError):
            await store.flush_customer("C001")
        assert calls == ["C001"]
    finally:
        release.set()
        await asyncio.gather(*list(store._jobs.values()))
    assert store.pending_customers() == []


@pytest.mark.asyncio
async def test_shutdown_flushes_new_customer_and_stops_worker():
    client, remote, store, _ = setup_store()
    store.load("C001")
    await store.start()
    await store.close()
    assert store._worker is None
    assert remote.has_current("C001")
    assert ("private", "users/C001/foresights/.keep") in client.objects


@pytest.mark.asyncio
async def test_archive_search_uses_pending_ram_content():
    _, remote, store, _ = setup_store()
    snapshot = store.load("C001")
    snapshot["episodes"] = [{"source": "episode-2026-10-17.md", "content": "new call"}]
    store.save_snapshot("C001", snapshot)
    assert store.search_archive("C001", "new call", day="2026-10-17")["hits"][0]["content"] == "new call"
    assert store.search_archive("C001", "new call")["hits"][0]["content"] == "new call"
    assert remote.load("C001") == empty_snapshot("C001")


@pytest.mark.asyncio
async def test_account_end_only_marks_ended_after_successful_upload(monkeypatch):
    from telesale_agent.entrypoints.api import chat, conversations
    from fastapi import HTTPException

    events = []
    async def flush(_):
        events.append("upload")
        if len(events) == 1:
            raise RuntimeError("offline")
    state = ConversationState(str(uuid4()), identity=CustomerIdentity(customer_id="C001"))
    repository = SimpleNamespace(load_state=AsyncMock(return_value=state), end_conversation=AsyncMock())
    monkeypatch.setattr(chat, "harness", SimpleNamespace(memory=SimpleNamespace(flush_customer=flush)))
    with pytest.raises(HTTPException) as failure:
        await conversations.end_conversation(state.conversation_id, {"id": "owner"}, repository)
    assert failure.value.status_code == 503
    repository.end_conversation.assert_not_awaited()
    result = await conversations.end_conversation(state.conversation_id, {"id": "owner"}, repository)
    assert result == {"status": "ended"}
    repository.end_conversation.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_journal_stays_prepared_until_remote_flush_and_can_replay():
    from telesale_agent.application.memory.coordinator import commit_voice

    client, remote, store, _ = setup_store()
    context = make_context(store.load("C001"), deltas={"size": 39})
    job = {"status": "pending", "prepared": None}
    async def prepared(_, batch):
        job.update(status="prepared", prepared=batch)
    async def committed(_):
        job["status"] = "committed"
    journal = SimpleNamespace(get=AsyncMock(return_value=job), prepared=prepared, committed=committed)
    services = SimpleNamespace(memory=store, persist=TurnMemoryPersister(store), customer_context=None)
    await commit_voice(services, context, journal, "voice:test")
    assert job["status"] == "prepared"
    assert client.put_count == 0

    # Simulate losing RAM before session end: the durable prepared operations
    # can still be replayed by the existing recovery flow after a restart.
    restarted = BufferedCustomerMemoryStore(remote)
    services.memory = restarted
    services.persist = TurnMemoryPersister(restarted)
    replay_context = make_context(restarted.load("C001"), deltas={})
    await commit_voice(services, replay_context, journal, "voice:test")
    assert job["status"] == "prepared"
    await restarted.flush_customer("C001")
    assert job["status"] == "committed"
    assert remote.load("C001")["facts"] == {"size": 39}


@pytest.mark.asyncio
async def test_ending_uncached_customer_after_restart_is_a_noop():
    client, _, store, _ = setup_store()
    await store.flush_customer("C050")
    assert client.put_count == 0


@pytest.mark.asyncio
async def test_first_account_turn_passes_trusted_email_without_phone(monkeypatch):
    from telesale_agent.entrypoints.api import chat
    from telesale_agent.core.models import TurnInput

    key = str(uuid4())
    state = ConversationState(key)
    observed = []
    async def run(turn, current):
        observed.append(dict(turn.metadata))
        current.identity = CustomerIdentity(customer_id="C051")
        return SimpleNamespace(state=current, response_text="Xin chào")
    repository = SimpleNamespace(
        load_state=AsyncMock(return_value=state),
        identity_contact=AsyncMock(return_value={"account_email": "owner@gmail.com", "account_name": "Khách"}),
        save_turn=AsyncMock(return_value={}),
    )
    monkeypatch.setattr(chat, "harness", SimpleNamespace(run_turn=run))
    monkeypatch.setattr(chat, "turn_payload", lambda turn, result: {"response": result.response_text, "call_brief": None})
    monkeypatch.setattr(chat.provider_cooldown, "remaining", lambda: 0)
    await chat.run_chat_turn(TurnInput(key, text="Xin chào", metadata={"account_email": "untrusted@example.com"}),
                             repository=repository, user_id="owner")
    assert observed[0]["account_email"] == "owner@gmail.com"
    repository.identity_contact.assert_awaited_once_with("owner")
