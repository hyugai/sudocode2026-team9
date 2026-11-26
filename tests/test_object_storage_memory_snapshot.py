from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from langchain.tools import ToolRuntime

from telesale_agent.adapters.memory.object_storage import ObjectStorageCustomerMemoryRepository
from telesale_agent.adapters.memory.in_memory import InMemoryCustomerMemoryRepository
from telesale_agent.adapters.memory.turn_persist import TurnMemoryPersister
from telesale_agent.adapters.llm import llm_persist
from telesale_agent.application.deepagent.tools.memory_archive import build_memory_archive_tool
from telesale_agent.application.deepagent.tools.routing import (
    _request_size_estimate,
    select_tools_for_turn,
)
from telesale_agent.application.memory.snapshot import empty_snapshot
from telesale_agent.core.models import (
    ConversationState,
    CustomerIdentity,
    TurnContext,
    TurnInput,
)


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.get_count = 0
        self.put_count = 0
        self.fail_put = False

    def get_object(self, *, Bucket, Key):
        self.get_count += 1
        try:
            return {"Body": BytesIO(self.objects[(Bucket, Key)])}
        except KeyError as exc:
            raise MissingObject from exc

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.put_count += 1
        if self.fail_put:
            raise RuntimeError("upload failed")
        assert ContentType.startswith("text/markdown")
        self.objects[(Bucket, Key)] = Body.read()

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, ContinuationToken=None):
        keys = sorted(key for bucket, key in self.objects if bucket == Bucket and key.startswith(Prefix))
        return {"Contents": [{"Key": key} for key in keys[:MaxKeys]]}


def make_context(snapshot, *, deltas, call_date=None):
    state = ConversationState(
        conversation_id="call-1",
        customer_memory=snapshot,
        memory_deltas=deltas,
    )
    context = TurnContext(
        input=TurnInput(conversation_id="call-1", text="Giày đen size 39"),
        state=state,
        identity=CustomerIdentity(customer_id="C001"),
    )
    if call_date:
        context.input.metadata["call_date"] = call_date
    return context


def make_callback_context(result):
    context = make_context(
        empty_snapshot("C001"),
        deltas={
            "callback_at": "10 giờ ngày 2026-10-17",
            "callback_requested_at": "2026-10-17T10:00:00",
            "blocker": "cần hỏi người nhà",
        },
    )
    context.steps.append(
        SimpleNamespace(
            plan=SimpleNamespace(tool_name="schedule.callback", arguments={}),
            action_result=SimpleNamespace(output=result),
        )
    )
    return context


@pytest.mark.asyncio
async def test_scheduler_result_wins_over_customer_requested_callback_time():
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=FakeS3())
    context = make_callback_context(
        {
            "callback_id": "CB-123456",
            "callback_at": "2026-10-19T10:00:00",
            "moved_from": "2026-10-17T10:00:00",
        }
    )

    writes = await TurnMemoryPersister(repository).persist(context)
    facts = repository.load("C001")["facts"]

    assert facts["callback_at"] == "2026-10-19T10:00:00"
    assert facts["callback_requested_at"] == "2026-10-17T10:00:00"
    assert facts["blocker"] == "cần hỏi người nhà"
    assert {write["key"]: write["provenance"] for write in writes} == {
        "callback_at": "verified_tool",
        "callback_requested_at": "verified_tool",
        "blocker": "customer",
    }


@pytest.mark.asyncio
async def test_failed_scheduler_does_not_save_request_as_confirmed_callback():
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=FakeS3())
    context = make_callback_context({"error": "scheduler_unavailable"})

    await TurnMemoryPersister(repository).persist(context)

    facts = repository.load("C001")["facts"]
    assert "callback_at" not in facts
    assert facts["callback_requested_at"] == "2026-10-17T10:00:00"


@pytest.mark.asyncio
async def test_unmoved_callback_still_uses_verified_tool_timestamp():
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=FakeS3())
    context = make_callback_context(
        {"callback_id": "CB-123456", "callback_at": "2026-10-17T10:00:00"}
    )

    writes = await TurnMemoryPersister(repository).persist(context)

    assert repository.load("C001")["facts"]["callback_at"] == "2026-10-17T10:00:00"
    assert next(write for write in writes if write["key"] == "callback_at")[
        "provenance"
    ] == "verified_tool"


@pytest.mark.asyncio
async def test_first_export_creates_tree_and_later_export_updates_changed_files(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    snapshot = repository.load("C001")
    context = make_context(snapshot, deltas={"size": 39, "color": "den"})

    writes = await TurnMemoryPersister(repository).persist(context)

    assert {write["key"] for write in writes} == {"size", "color"}
    # The first access also checks the legacy key; an existing current.md is one GET.
    assert client.get_count == 2
    assert client.put_count == 7  # 3 static files, 3 folder markers, current.md
    assert ("private", "users/C001/facts.md") in client.objects
    assert ("private", "users/C001/user.md") in client.objects
    assert ("private", "users/C001/behaviors.md") in client.objects
    assert ("private", "users/C001/episodes/.keep") in client.objects
    assert list(tmp_path.iterdir()) == []
    assert client.objects[("private", "users/C001/current.md")].startswith(
        b"# Customer Memory\n"
    )
    before = client.get_count
    assert repository.load("C001")["facts"] == {"size": 39, "color": "den"}
    assert client.get_count == before + 1
    second = make_context(repository.load("C001"), deltas={"size": 40})
    before_put = client.put_count
    await TurnMemoryPersister(repository).persist(second)
    assert client.put_count == before_put + 2  # facts.md and current.md
    assert b'"size": 40' in client.objects[("private", "users/C001/current.md")]
    assert b'size: 40' in client.objects[("private", "users/C001/facts.md")]


@pytest.mark.asyncio
async def test_failed_upload_removes_draft_and_preserves_deltas(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    client = FakeS3()
    client.fail_put = True
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    context = make_context(empty_snapshot("C001"), deltas={"size": 39})

    with pytest.raises(RuntimeError, match="upload failed"):
        await TurnMemoryPersister(repository).persist(context)

    assert list(tmp_path.iterdir()) == []
    assert context.state.memory_deltas == {"size": 39}
    assert context.state.customer_memory == empty_snapshot("C001")


def test_rejects_other_customer_and_invalid_object():
    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)

    with pytest.raises(ValueError):
        repository.save_snapshot("C001", empty_snapshot("C002"))
    with pytest.raises(ValueError):
        repository.load("../other")

    client.objects[("private", "users/C001/current.md")] = b"not memory"
    with pytest.raises(ValueError, match="Invalid customer memory"):
        repository.load("C001")


def test_object_storage_prefix_isolates_benchmark_customer(monkeypatch):
    monkeypatch.setenv("CUSTOMER_MEMORY_PREFIX", "eval/benchmark_v37/users")
    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    repository.save_snapshot("C001", empty_snapshot("C001"))
    assert ("private", "eval/benchmark_v37/users/C001/current.md") in client.objects
    assert ("private", "users/C001/current.md") not in client.objects


def test_archives_old_days_before_replacing_current():
    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    snapshot = empty_snapshot("C001")
    snapshot["episodes"] = [
        {"source": f"episode-2026-10-{day:02d}.md", "content": f"day {day}\n"}
        for day in (1, 2, 3)
    ]
    repository.save_snapshot("C001", snapshot)

    assert client.objects[("private", "users/C001/episodes/episode-2026-10-01.md")] == b"day 1\n"
    assert repository.load_archive("C001", "episodes", "2026-10-01") == "day 1\n"
    assert [item["source"] for item in repository.load("C001")["episodes"]] == [
        "episode-2026-10-02.md", "episode-2026-10-03.md"
    ]
    assert client.put_count >= 4  # All dated files are physically present.
    assert ("private", "users/C001/episodes/episode-2026-10-02.md") in client.objects
    assert ("private", "users/C001/episodes/episode-2026-10-03.md") in client.objects


def test_reads_legacy_single_object_until_first_new_commit():
    from telesale_agent.application.memory.snapshot import render_snapshot

    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    old = empty_snapshot("C001")
    old["facts"]["size"] = 39
    client.objects[("private", "customer-memory/C001.md")] = render_snapshot(old).encode()

    assert repository.load("C001")["facts"]["size"] == 39
    repository.save_snapshot("C001", old)
    assert repository.load("C001")["facts"]["size"] == 39
    assert ("private", "users/C001/current.md") in client.objects


def test_backfill_existing_current_without_replacing_live_facts():
    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    live = empty_snapshot("C031")
    live["facts"]["size"] = 40
    repository.save_snapshot("C031", live)
    current_before = client.objects[("private", "users/C031/current.md")]
    local = empty_snapshot("C031")
    local["episodes"] = [{"source": "episode-2026-02-17.md", "content": "Old call\n"}]
    local["atomic_facts"] = [{"source": "fact-2026-02-17.md", "content": "- old fact\n"}]
    client.objects.pop(("private", "users/C031/episodes/.keep"))

    uploaded = repository.backfill_files("C031", local)

    assert uploaded >= 2
    assert client.objects[("private", "users/C031/current.md")] == current_before
    assert repository.load("C031")["facts"]["size"] == 40
    assert client.objects[("private", "users/C031/episodes/episode-2026-02-17.md")] == b"Old call\n"
    result = repository.search_archive("C031", "Old call", section="episodes")
    assert result["hits"][0]["source"] == "episodes/episode-2026-02-17.md"


def test_archive_search_prefers_fresher_current_day():
    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    original = empty_snapshot("C031")
    original["episodes"] = [{"source": "episode-2026-10-17.md", "content": "Old draft"}]
    repository.save_snapshot("C031", original)
    updated = empty_snapshot("C031")
    updated["episodes"] = [{"source": "episode-2026-10-17.md", "content": "New full episode"}]
    repository.save_snapshot("C031", updated, previous_snapshot=original)

    assert client.objects[("private", "users/C031/episodes/episode-2026-10-17.md")] == b"New full episode"
    # Simulate an older mirror from a previous deployment.
    client.objects[("private", "users/C031/episodes/episode-2026-10-17.md")] = b"Old draft"
    result = repository.search_archive("C031", "full episode", section="episodes", day="2026-10-17")
    assert result["hits"][0]["content"] == "New full episode"


def test_new_call_day_flushes_completed_previous_day():
    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    first = empty_snapshot("C001")
    first["episodes"] = [{"source": "episode-2026-10-15.md", "content": "Early note"}]
    repository.save_snapshot("C001", first)
    second = empty_snapshot("C001")
    second["episodes"] = [
        {"source": "episode-2026-10-15.md", "content": "Complete first call"},
        {"source": "episode-2026-10-17.md", "content": "Second call"},
    ]
    second["facts"]["blocker"] = "family"
    repository.save_snapshot("C001", second, previous_snapshot=first)

    assert repository.load_archive("C001", "episodes", "2026-10-15") == "Complete first call"
    assert len(repository.load("C001")["episodes"]) == 2
    assert b'"family"' in client.objects[("private", "users/C001/facts.md")]


def test_archive_tool_does_not_expose_customer_id_as_model_argument():
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=FakeS3())
    archive_tool = build_memory_archive_tool(repository)
    assert archive_tool.name == "search_customer_memory_archive"
    assert "customer_id" not in archive_tool.args
    assert "runtime" not in archive_tool.args
    estimate = _request_size_estimate(
        SimpleNamespace(system_message=SimpleNamespace(content="test"), messages=[]),
        [archive_tool],
    )
    assert estimate["tool_chars"] > 0


def test_history_question_exposes_archive_lookup():
    assert "search_customer_memory_archive" in select_tools_for_turn(
        None, "Lần trước tôi đã hỏi mã serial gì?"
    )


@pytest.mark.asyncio
async def test_archive_tool_uses_runtime_customer_identity():
    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    client.objects[("private", "users/C031/episodes/episode-2026-02-17.md")] = b"C031 old call"
    client.objects[("private", "users/C032/episodes/episode-2026-02-17.md")] = b"C032 secret"
    archive_tool = build_memory_archive_tool(repository)
    runtime = ToolRuntime(
        state={}, context={"customer_id": "C031"}, config={},
        stream_writer=lambda _: None, tool_call_id="memory-1", store=None,
    )

    result = await archive_tool.coroutine("old call", runtime, "episodes", "2026-02-17")

    assert "C031 old call" in result["hits"][0]["content"]
    assert "C032" not in str(result)


def test_turn_workspace_groups_episodes_by_day():
    memory = InMemoryCustomerMemoryRepository(daily_files=True)
    memory.record_episode("C001", "First call", occurred_on="2026-10-17", source_id="call-1")
    memory.record_episode("C001", "Second call", occurred_on="2026-10-17", source_id="call-2")
    memory.record_episode("C001", "First call", occurred_on="2026-10-17", source_id="call-1")

    episodes = memory.load("C001")["episodes"]
    assert len(episodes) == 1
    assert episodes[0]["source"] == "episode-2026-10-17.md"
    assert episodes[0]["content"].count("First call") == 1
    assert "Second call" in episodes[0]["content"]


def test_failed_archive_does_not_replace_current():
    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    snapshot = empty_snapshot("C001")
    snapshot["foresights"] = [
        {"source": f"foresight-2026-10-{day:02d}.md", "content": f"- day {day}\n"}
        for day in (1, 2, 3)
    ]
    client.fail_put = True

    with pytest.raises(RuntimeError, match="upload failed"):
        repository.save_snapshot("C001", snapshot)

    assert ("private", "users/C001/current.md") not in client.objects


@pytest.mark.asyncio
async def test_llm_learning_layers_create_daily_archive_files(monkeypatch):
    class StructuredModel:
        async def ainvoke(self, _messages):
            return llm_persist.EpisodeSummarySchema(
                facts_established="Khách cần giày đen size 39.",
                product_advised="",
                blocker="",
                foresights=["Xác nhận nhu cầu đặt hàng ở lượt sau."],
            )

    class Model:
        def with_structured_output(self, _schema):
            return StructuredModel()

    monkeypatch.setattr(llm_persist, "create_chat_model", lambda **_: Model())
    client = FakeS3()
    repository = ObjectStorageCustomerMemoryRepository(bucket="private", client=client)
    context = make_context(
        repository.load("C001"), deltas={"size": 39}, call_date="2026-10-15"
    )

    await llm_persist.LLMPersister(repository).persist(context)

    assert client.get_count == 2
    assert client.put_count >= 7
    assert any(key.startswith("users/C001/episodes/episode-") for _, key in client.objects)
    assert any(key.startswith("users/C001/atomic_facts/fact-") for _, key in client.objects)
    assert any(key.startswith("users/C001/foresights/foresight-") for _, key in client.objects)
    learned = repository.load("C001")
    assert learned["facts"]["size"] == 39
    assert len(learned["atomic_facts"]) == 1
    assert len(learned["episodes"]) == 1
    assert len(learned["foresights"]) == 1
    assert learned["episodes"][0]["source"] == "episode-2026-10-15.md"
    assert learned["atomic_facts"][0]["source"] == "fact-2026-10-15.md"
    assert learned["foresights"][0]["source"] == "foresight-2026-10-15.md"
