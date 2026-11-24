"""Backend learning with isolated SQL/object storage and no provider calls."""
import asyncio
from datetime import timedelta
import io
import json
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import create_engine, select, update

from self_agent.adapters.object_memory import ObjectStorageAgentMemory
from self_agent.backend import BackendLearning, build_backend_learning
from self_agent.config import LearningConfig
from self_agent.lesson_runtime import CURRENT_LESSONS, LessonAgent
from self_agent.service import SelfLearningService
from telesale_agent.adapters.db.learning import LearningRepository, jobs, migrate_learning, now, sessions, session_key
from telesale_agent.adapters.db.voice_store import VoiceStore, metadata as voice_metadata
from telesale_agent.core.models import CallBrief, ConversationState, CustomerIdentity, Message, TurnInput


def lesson(key="a"):
    return {"id": key, "status": "approved", "scope": "general", "version": 2,
            "mechanism": "knowledge_gap", "source_refs": [], "title": "Verify policy conditions",
            "when": "A customer asks about a policy condition.",
            "do": "Use the applicable authoritative source before stating the condition.",
            "otherwise": "Explain which information has not been verified.", "triggers": ["policy"]}


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class ObjectClient:
    def __init__(self):
        self.objects = {}
        self.fail_put = False
        self.fail_get = False

    def put_object(self, *, Bucket, Key, Body, ContentType):
        if self.fail_put:
            raise OSError("private provider failure")
        self.objects[Key] = Body

    def get_object(self, *, Bucket, Key):
        if self.fail_get:
            raise OSError("private provider failure")
        if Key not in self.objects:
            raise MissingObject()
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, *, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(key for key in self.objects if key.startswith(Prefix))
        offset = int(ContinuationToken or 0)
        # Small pages exercise pagination for lesson banks and artifacts.
        page = {"Contents": [{"Key": key} for key in keys[offset:offset + 1]],
                "IsTruncated": offset + 1 < len(keys)}
        if page["IsTruncated"]:
            page["NextContinuationToken"] = str(offset + 1)
        return page


def state(cid="chat", number=1):
    return ConversationState(
        conversation_id=cid, turn_number=number,
        identity=CustomerIdentity(customer_id="C1", phone="0901234567", profile={"name": "Nguyễn An"}),
        call_brief=CallBrief(customer_id="C1", open_questions=["Bảo hành áp dụng thế nào?"]),
        messages=[Message("user", f"Nguyễn An hỏi chính sách lượt {number}, 0901234567"),
                  Message("agent", f"Cần kiểm chứng lượt {number}.")])


def result(s):
    return NS(state=s, conversation_id=s.conversation_id, turn_number=s.turn_number,
              response_text=s.messages[-1].content, retrieved=None,
              tool_calls=[{"name": "search_policy", "args": {"query": "policy"},
                           "result": {"phone": "0901234567", "content": "Verified source"}}])


class BackendLearningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + self.temporary.name.replace("\\", "/") + "/learning.db",
                                    connect_args={"check_same_thread": False})
        migrate_learning(self.engine)
        self.repository = LearningRepository(self.engine)
        self.client = ObjectClient()
        self.memory = ObjectStorageAgentMemory(bucket="test", client=self.client)
        self.config = LearningConfig(enabled=True)
        self.base = NS(agent=NS(ainvoke=AsyncMock(return_value={"messages": []})), mcp_tools={})
        self.service = BackendLearning(self.base, engine=self.engine, memory=self.memory, config=self.config,
                                       routing_model=NS(json=AsyncMock(return_value={"selected_ids": ["a"]})))

    async def asyncTearDown(self):
        await self.service.close()
        self.engine.dispose()
        self.temporary.cleanup()

    def job_rows(self):
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(select(jobs)).mappings()]

    async def save(self, s, channel="guest"):
        if channel == "guest":
            await self.service.save_guest(s, result(s))
        else:
            hook = self.service.save_hook(channel, s, result(s))
            with self.engine.begin() as connection:
                hook(connection)

    async def test_complete_history_survives_tail_ram_and_end_is_idempotent(self):
        for number in range(1, 26):
            s = state(number=number)
            await self.save(s)
        first = await self.service.end_guest(s)
        second = await self.service.end_guest(s)
        self.assertEqual(first.job_id, second.job_id)
        self.assertEqual(len(self.job_rows()), 1)
        data = self.job_rows()[0]["snapshot"]
        self.assertEqual(len(data["messages"]), 50)
        self.assertEqual(len(data["turn_evidence"]), 25)
        self.assertEqual([e["turn_id"] for e in data["turn_evidence"]], list(range(1, 26)))
        self.assertEqual(data["evidence_coverage"], "per_turn_evidence")
        self.assertNotIn("0901234567", json.dumps(data, ensure_ascii=False))
        self.assertNotIn("Nguyễn An", json.dumps(data, ensure_ascii=False))
        with self.assertRaises(ValueError):
            await self.service.restore_guest("chat")

    async def test_guest_checkpoint_restores_after_process_restart(self):
        s = state()
        await self.save(s)
        restored = await self.service.restore_guest("chat")
        self.assertEqual(restored, s)
        restarted = SelfLearningService(config=self.config, memory=self.memory,
                                        repository=LearningRepository(self.engine))
        self.assertEqual(await restarted.restore_guest("chat"), s)
        with self.engine.begin() as connection:
            connection.execute(update(sessions).values(checkpoint=None))
        # Durable evidence still allows the terminal job after RAM loss.
        await restarted.end_guest(ConversationState("chat"))
        self.assertEqual(len(self.job_rows()[0]["snapshot"]["messages"]), 2)

    async def test_pending_guest_write_is_retried_before_end(self):
        self.service.repository = self.repository
        with patch.object(self.repository, "save_turn", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                await self.service.save_guest(state(), result(state()))
        self.assertTrue(self.service.pending_guest)
        await self.service.flush_guest("chat")
        await self.service.end_guest(state())
        self.assertEqual(len(self.job_rows()[0]["snapshot"]["messages"]), 2)
        self.assertFalse(self.service.pending_guest)

    async def test_account_transaction_rolls_back_history_evidence_and_job(self):
        s = state()
        with self.assertRaises(RuntimeError):
            with self.engine.begin() as connection:
                self.service.save_hook("account", s, result(s))(connection)
                self.service.queue_in_transaction(connection, "account", s)
                raise RuntimeError("transaction aborted")
        self.assertEqual(self.job_rows(), [])
        self.assertIsNone(self.repository.get_session(session_key("account", "chat")))

    async def test_account_full_messages_and_feedback_are_captured_without_tail_assumption(self):
        s = state()
        history = [{"role": "user", "content": "Câu hỏi cũ"}, {"role": "agent", "content": "Câu trả lời cũ"},
                   {"role": "user", "content": "Nguyễn An hỏi tiếp"}, {"role": "agent", "content": "Chưa rõ"}]
        with self.engine.begin() as connection:
            self.service.queue_in_transaction(connection, "account", s, messages=history,
                                               feedback=[{"comment": "Nguyễn An, 0901234567", "rating": "negative"}])
        data = self.job_rows()[0]["snapshot"]
        self.assertEqual(len(data["messages"]), 4)
        self.assertEqual(data["revision"], 2)
        self.assertEqual(data["evidence_coverage"], "transcript_only")
        self.assertEqual(data["feedback"][0]["rating"], "negative")
        self.assertNotIn("Nguyễn An", json.dumps(data, ensure_ascii=False))

    async def test_bank_is_frozen_per_conversation_and_context_is_isolated(self):
        first, second = state("first"), state("second")
        turn = lambda s: TurnInput(s.conversation_id, text="policy")
        token = await self.service.begin_chat("guest", turn(first), first)
        self.service.reset_chat(token)
        self.memory.write_lesson(lesson())
        token = await self.service.begin_chat("guest", turn(second), second)
        self.assertEqual(CURRENT_LESSONS.get()["lessons"][0]["id"], "a")
        self.service.reset_chat(token)
        token = await self.service.begin_chat("guest", turn(first), first)
        self.assertEqual(CURRENT_LESSONS.get()["lessons"], [])
        self.service.reset_chat(token)
        self.assertIsNone(CURRENT_LESSONS.get())

    async def test_unavailable_bank_or_router_does_not_fail_chat(self):
        with patch.object(self.memory, "load_lessons", side_effect=OSError("private contents")):
            s = state()
            token = await self.service.begin_chat("guest", TurnInput("chat", text="policy"), s)
            self.assertEqual(CURRENT_LESSONS.get()["lessons"], [])
            self.service.reset_chat(token)
        self.memory.write_lesson(lesson())
        self.service.routing_model.json.side_effect = RuntimeError("private contents")
        s = state("other")
        turn = TurnInput("other", text="policy")
        token = await self.service.begin_chat("guest", turn, s)
        self.assertEqual(CURRENT_LESSONS.get()["lessons"], [])
        self.assertEqual(turn.metadata["lesson_trace"]["routing_error"], "RuntimeError")
        self.service.reset_chat(token)

    async def test_retry_backoff_terminal_failure_and_running_recovery(self):
        await self.save(state())
        await self.service.end_guest(state())
        self.service.learner = NS(process=AsyncMock(side_effect=RuntimeError("private transcript")))
        for attempt, expected in [(1, "queued"), (2, "queued"), (3, "failed")]:
            job = self.repository.claim(3)
            self.assertEqual(job["attempts"], attempt)
            await self.service._process(job)
            row = self.job_rows()[0]
            self.assertEqual(row["status"], expected)
            self.assertEqual(row["error"], "RuntimeError")
            self.assertNotIn("private transcript", str(row))
            if attempt < 3:
                self.assertIsNone(self.repository.claim(3))
                with self.engine.begin() as connection:
                    connection.execute(update(jobs).values(retry_at=now() - timedelta(seconds=1)))
        # Simulate a process dying in its last allowed attempt.
        with self.engine.begin() as connection:
            connection.execute(update(jobs).values(status="running", attempts=3))
        self.repository.recover_jobs()
        self.assertEqual(self.repository.claim(3)["attempts"], 3)

    async def test_worker_processes_durable_job_and_restores_wrapped_agent_on_close(self):
        await self.save(state())
        queued = await self.service.end_guest(state())
        self.service.learner = NS(process=AsyncMock(return_value={"outcome": "no_candidates"}))
        original = self.base.agent
        await self.service.start()
        for _ in range(100):
            if self.repository.get_job(queued.job_id)["status"] == "done":
                break
            await asyncio.sleep(.01)
        self.assertEqual(self.repository.get_job(queued.job_id)["status"], "done")
        await self.service.close()
        self.assertIs(self.base.agent, original)

    async def test_object_write_failure_retries_without_duplicate_lessons(self):
        await self.save(state())
        await self.service.end_guest(state())
        async def learn(*args):
            await asyncio.to_thread(self.memory.write_lesson, lesson())
            await asyncio.to_thread(self.memory.write, "reports", "a", {"outcome": "done"})
            return {}
        self.service.learner = NS(process=learn)
        self.client.fail_put = True
        await self.service._process(self.repository.claim(3))
        self.assertEqual(self.job_rows()[0]["status"], "queued")
        self.client.fail_put = False
        with self.engine.begin() as connection:
            connection.execute(update(jobs).values(retry_at=now() - timedelta(seconds=1)))
        await self.service._process(self.repository.claim(3))
        self.assertEqual(self.job_rows()[0]["status"], "done")
        self.assertEqual(len(self.memory.load_lessons()), 1)

    async def test_voice_finalization_waits_for_journal_and_never_routes_lessons(self):
        voice_metadata.create_all(self.engine)
        store = VoiceStore(self.engine)
        s = state("live-example")
        await self.service.register_voice(s)
        def payload(number, *, finished=True, interrupted=False):
            raw = {"conversation_id": s.conversation_id, "phone": "0901234567", "turn_number": number,
                   "input_text": "Nguyễn An hỏi chính sách", "input_finished": finished,
                   "output_text": "Cần kiểm chứng", "interrupted": interrupted, "tools": []}
            raw["learning"] = self.service.capture_voice_turn(s, raw)
            return raw
        await store.save("voice:example:a", "C1", payload(1), status="pending")
        await store.save("voice:example:b", "C1", payload(2, interrupted=True), status="committed")
        await store.save("voice:example:c", "C1", payload(3, finished=False), status="incomplete")
        await self.service.finalize_voice(s)
        with patch("telesale_agent.application.realtime.controller.recover_memory", new_callable=AsyncMock):
            await self.service.recover_voice()
            self.assertEqual(self.job_rows(), [])
            await store.committed("voice:example:a")
            await self.service.recover_voice()
            await self.service.recover_voice()
        self.assertEqual(len(self.job_rows()), 1)
        data = self.job_rows()[0]["snapshot"]
        self.assertEqual(len(data["messages"]), 4)
        self.assertTrue(data["turn_evidence"][1]["interrupted"])
        self.assertNotIn("Nguyễn An", json.dumps(data, ensure_ascii=False))
        self.assertNotIn("0901234567", json.dumps(data))
        self.service.routing_model.json.assert_not_awaited()

    async def test_disabled_backend_does_not_create_storage_or_worker(self):
        with patch.dict(os.environ, {"KNOWLEDGE_GAP_LOOP_ENABLED": "false"}), patch(
            "self_agent.adapters.object_memory.ObjectStorageAgentMemory", side_effect=AssertionError("No storage")):
            self.assertIsNone(await build_backend_learning(self.base, self.engine))
        disabled = SelfLearningService(config=LearningConfig(enabled=False))
        self.assertEqual((await disabled.end_session(None)).status, "disabled")
        self.assertIsNone(disabled.memory)
        self.assertIsNone(disabled.worker)

    async def test_unfinished_voice_output_is_not_presented_as_a_completed_answer(self):
        record = self.service.capture_voice_turn(state("live-partial"), {
            "input_text": "Chính sách?", "output_text": "Điều kiện là", "input_finished": True,
            "interrupted": False, "output_complete": False, "tools": []})
        self.assertFalse(record["evidence"]["output_complete"])
        self.assertIn("chưa hoàn tất", record["messages"][1]["content"])

    async def test_oversized_snapshot_keeps_session_active_without_truncation(self):
        from telesale_agent.adapters.db.learning import LearningSnapshotTooLarge
        s = state()
        await self.save(s, "account")
        history = [{"role": "user", "content": "a" * 512001}]
        with self.assertRaises(LearningSnapshotTooLarge):
            with self.engine.begin() as connection:
                self.service.queue_in_transaction(connection, "account", s, messages=history)
        self.assertEqual(self.job_rows(), [])
        self.assertEqual(self.repository.get_session(session_key("account", "chat"))["status"], "active")
        self.assertEqual(len(history[0]["content"]), 512001)

    async def test_migration_repeats_without_loss_and_rejects_incompatible_tables(self):
        await self.save(state())
        await self.service.end_guest(state())
        migrate_learning(self.engine)
        self.repository.ready()
        self.assertEqual(len(self.job_rows()), 1)
        from sqlalchemy import text
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE unrelated_business (id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO unrelated_business VALUES (7)"))
        migrate_learning(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT id FROM unrelated_business")), 7)
        incompatible = create_engine("sqlite://")
        try:
            with incompatible.begin() as connection:
                connection.execute(text("CREATE TABLE learning_jobs (id INTEGER PRIMARY KEY)"))
            with self.assertRaisesRegex(ValueError, "learning_jobs"):
                migrate_learning(incompatible)
        finally:
            incompatible.dispose()


class ObjectMemoryTests(unittest.TestCase):
    def test_pagination_roundtrip_tamper_rejection_and_prefix_isolation(self):
        client = ObjectClient()
        memory = ObjectStorageAgentMemory(bucket="test", client=client)
        for key in ("a", "b"):
            card = lesson(key)
            if key == "b":
                card["do"] = "Ask for clarification before making an unverified commitment."
            memory.write_lesson(card)
            memory.write("reports", key, {"id": key})
        self.assertEqual(len(memory.load_lessons()), 2)
        self.assertEqual(len(memory.records("reports")), 2)
        self.assertEqual(memory.read("reports", "a"), {"id": "a"})
        path = next(key for key in client.objects if key.endswith("a.md"))
        client.objects[path] += b"tampered"
        self.assertEqual([card["id"] for card in memory.load_lessons()], ["b"])
        with self.assertRaises(FileNotFoundError):
            memory.read("reports", "c")
        for prefix in ("users", "users/customer", "../agents", ""):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                ObjectStorageAgentMemory(bucket="test", client=client, prefix=prefix)


class LearningHttpTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from telesale_agent.entrypoints.api import chat
        self.chat = chat
        self.temporary = TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + self.temporary.name.replace("\\", "/") + "/http.db",
                                    connect_args={"check_same_thread": False})
        migrate_learning(self.engine)
        self.memory = ObjectStorageAgentMemory(bucket="test", client=ObjectClient())
        self.memory.write_lesson(lesson())
        self.routing = NS(json=AsyncMock(return_value={"selected_ids": ["a"]}))
        self.base = NS(agent=NS(ainvoke=AsyncMock(return_value={"messages": []})), mcp_tools={})
        self.service = BackendLearning(self.base, engine=self.engine, memory=self.memory,
                                       config=LearningConfig(enabled=True), routing_model=self.routing)
        self.base.agent = LessonAgent(self.base.agent)
        self.traces = []
        async def run(turn, current, *, on_text=None, on_status=None):
            if turn.audio:
                turn.text = "Điều kiện bảo hành từ bản ghi âm"
            current.identity = CustomerIdentity(customer_id="C1")
            current.turn_number += 1
            current.messages.extend([Message("user", turn.text), Message("agent", "Cần kiểm chứng")])
            await self.base.agent.ainvoke({"messages": []})
            self.traces.append(dict(turn.metadata["lesson_trace"]))
            if on_text:
                await on_text("Cần kiểm chứng")
            return NS(**vars(result(current)), call_brief=current.call_brief, latency={})
        self.base.run_turn = AsyncMock(side_effect=run)
        self.repository = NS(conversation_exists=AsyncMock(return_value=False))
        self.previous_overrides = dict(chat.app.dependency_overrides)
        chat.app.dependency_overrides[chat.get_auth_repository] = lambda: self.repository
        self.patches = [patch.object(chat, "harness", self.base), patch.object(chat, "learning_service", self.service),
                        patch.object(chat, "sessions", {}), patch.object(chat, "session_locks", {}),
                        patch.dict(os.environ, {"API_KEY": ""}), patch.object(chat.provider_cooldown, "remaining", return_value=0)]
        for item in self.patches:
            item.start()
        # No lifespan: providers and worker are deliberately absent in HTTP tests.
        self.client = TestClient(chat.app)

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.chat.app.dependency_overrides.clear()
        self.chat.app.dependency_overrides.update(self.previous_overrides)
        self.engine.dispose()
        self.temporary.cleanup()

    def test_text_audio_stream_and_guest_end_share_one_durable_session(self):
        cid = "learning-http"
        text = self.client.post("/api/chat", json={"conversation_id": cid, "message": "Điều kiện bảo hành?"})
        self.assertEqual(text.status_code, 200, text.text)
        audio = self.client.post("/api/chat/audio", data={"conversation_id": cid},
                                 files={"file": ("test.wav", b"fake audio", "audio/wav")})
        self.assertEqual(audio.status_code, 200, audio.text)
        self.assertEqual(audio.json()["transcript"], "Điều kiện bảo hành từ bản ghi âm")
        requests = [call.args[1]["request"] for call in self.routing.json.await_args_list]
        self.assertIn("Điều kiện bảo hành từ bản ghi âm", requests)
        streamed = self.client.post("/api/chat", headers={"accept": "text/event-stream"},
                                     json={"conversation_id": cid, "message": "Xin xác nhận lại"})
        self.assertEqual(streamed.status_code, 200, streamed.text)
        self.assertIn("event: done", streamed.text)
        for _ in range(2):
            ended = self.client.delete("/api/sessions/" + cid)
            self.assertEqual(ended.status_code, 200, ended.text)
        with self.engine.connect() as connection:
            rows = list(connection.execute(select(jobs)).mappings())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["revision"], 3)
        self.assertEqual(len(rows[0]["snapshot"]["messages"]), 6)
        self.assertTrue(all(trace["injected"] for trace in self.traces))
        again = self.client.post("/api/chat", json={"conversation_id": cid, "message": "Replay"})
        self.assertEqual(again.status_code, 409)

    def test_failed_enqueue_keeps_guest_state_for_retry(self):
        cid = "learning-retry"
        self.assertEqual(self.client.post("/api/chat", json={"conversation_id": cid, "message": "Bảo hành?"}).status_code, 200)
        with patch.object(self.service.repository, "queue", side_effect=OSError("offline")):
            self.assertEqual(self.client.delete("/api/sessions/" + cid).status_code, 503)
        self.assertIn(cid, self.chat.sessions)
        self.assertEqual(self.client.delete("/api/sessions/" + cid).status_code, 200)
        self.assertNotIn(cid, self.chat.sessions)


class LearningPostgresTests(unittest.IsolatedAsyncioTestCase):
    """Opt-in real transactions, confined to a new disposable schema."""
    async def asyncSetUp(self):
        url = os.environ.get("APP_DATA_TEST_DATABASE_URL")
        if not url:
            self.skipTest("Set APP_DATA_TEST_DATABASE_URL for isolated PostgreSQL learning integration")
        from sqlalchemy.schema import CreateSchema
        from telesale_agent.adapters.db.app_schema import create_app_engine, migrate_app_data
        from telesale_agent.adapters.db.models import Customer
        from telesale_agent.adapters.db.app_repository import AppDataRepository
        self.schema = "learning_test_" + uuid4().hex
        self.admin = create_app_engine(url)
        self.engine = create_app_engine(url).execution_options(schema_translate_map={None: self.schema})
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.admin.dispose)
        with self.admin.begin() as connection:
            connection.execute(CreateSchema(self.schema))
        self.addCleanup(self.drop_schema)
        Customer.__table__.create(self.engine)
        with self.engine.begin() as connection:
            connection.execute(Customer.__table__.insert().values(customer_id="C1", name="Test", phone="0901234567"))
        migrate_app_data(self.engine)
        migrate_learning(self.engine)
        self.repo = AppDataRepository(self.engine)
        self.user = await self.repo.create_user("Test", "learning@example.com", "$argon2id$test-only")
        self.conversation = await self.repo.create_conversation(self.user["id"])
        self.service = SelfLearningService(config=LearningConfig(enabled=True), repository=LearningRepository(self.engine))

    def drop_schema(self):
        from sqlalchemy.schema import DropSchema
        assert self.schema.startswith("learning_test_") and len(self.schema) == len("learning_test_") + 32
        with self.admin.begin() as connection:
            connection.execute(DropSchema(self.schema, cascade=True))

    async def test_real_account_save_end_and_retry_are_atomic(self):
        s = state(self.conversation["id"])
        await self.repo.save_turn(self.user["id"], s, s.messages[0].content, s.messages[1].content, None,
                                  learning_hook=self.service.save_hook("account", s, result(s)))
        def broken(connection, messages, feedback):
            self.service.queue_in_transaction(connection, "account", s, messages=messages, feedback=feedback)
            raise RuntimeError("abort after enqueue")
        with self.assertRaises(RuntimeError):
            await self.repo.end_conversation(self.user["id"], s.conversation_id, learning_hook=broken)
        restored = await self.repo.load_state(self.user["id"], s.conversation_id, active_only=True)
        self.assertEqual(restored.turn_number, 1)
        with self.engine.connect() as connection:
            self.assertEqual(list(connection.execute(select(jobs))), [])
        def queue(connection, messages, feedback):
            self.service.queue_in_transaction(connection, "account", s, messages=messages, feedback=feedback)
        await self.repo.end_conversation(self.user["id"], s.conversation_id, learning_hook=queue)
        await self.repo.end_conversation(self.user["id"], s.conversation_id, learning_hook=queue)
        with self.engine.connect() as connection:
            rows = list(connection.execute(select(jobs)).mappings())
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["snapshot"]["messages"]), 2)
        migrate_learning(self.engine)  # Repeat migration preserves the job.
        self.assertEqual(self.service.repository.get_job(rows[0]["id"])["status"], "queued")

    async def test_real_account_evidence_failure_rolls_back_messages_and_checkpoint(self):
        s = state(self.conversation["id"])
        def broken(connection):
            self.service.save_hook("account", s, result(s))(connection)
            raise RuntimeError("abort evidence write")
        with self.assertRaises(RuntimeError):
            await self.repo.save_turn(self.user["id"], s, s.messages[0].content, s.messages[1].content, None,
                                      learning_hook=broken)
        restored = await self.repo.load_state(self.user["id"], s.conversation_id)
        self.assertEqual(restored.turn_number, 0)
        self.assertIsNone(self.service.repository.get_session(session_key("account", s.conversation_id)))


if __name__ == "__main__":
    unittest.main()
