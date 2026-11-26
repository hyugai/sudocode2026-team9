"""Unit tests plus opt-in PostgreSQL integration in a disposable private schema.

Set APP_DATA_TEST_DATABASE_URL explicitly to run DB tests. Existing schemas and
rows are never reset. No LLM, ASR, MCP, password service or customer files used.
"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import hashlib
import os
import unittest
from uuid import uuid4

from sqlalchemy import Column, MetaData, Table, Uuid, delete, event, func, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema, DropSchema

from telesale_agent.adapters.db.app_models import (
    APP_TABLES, AuthSession, ChatMessage, Conversation, MessageFeedback, User, utc_now,
)
from telesale_agent.adapters.db.app_repository import AppDataNotFound, AppDataRepository, ConversationConflict
from telesale_agent.adapters.db.app_schema import create_app_engine, migrate_app_data
from telesale_agent.adapters.db.checkpoint import (
    CheckpointError, CheckpointTooLargeError, deserialize_checkpoint, serialize_checkpoint,
)
from telesale_agent.adapters.db.models import Customer
from telesale_agent.core.models import CallBrief, ConversationState, CustomerIdentity, Message, RetrievedContext


def example_state(conversation_id: str) -> ConversationState:
    return ConversationState(
        conversation_id=conversation_id, turn_number=1,
        identity=CustomerIdentity(customer_id="TEST001", phone="0900000000", confidence=1.0),
        customer_profile={"name": "Khách mẫu"},
        customer_memory={"facts": {"budget_vnd": 3000000}},
        past_history={"past_orders": []},
        retrieved_data=RetrievedContext(knowledge=[{"text": "Bảo hành"}]),
        call_brief=CallBrief(customer_id="TEST001", summary="Tư vấn", needs=["Yên tĩnh"]),
        messages=[Message("user", "Xin chào"), Message("agent", "Chào bạn")],
        working_memory={"pending_order": {"sku": "TEST-SKU", "quantity": 2}},
        memory_deltas={"budget_vnd": 3000000},
    )


PREVIEW = {"summary": "Tư vấn", "needs": ["Yên tĩnh"], "objections": [], "unresolved_issues": []}


class CheckpointTests(unittest.TestCase):
    def test_roundtrip_restores_nested_dataclasses_and_independent_state(self):
        original = example_state(str(uuid4()))
        payload = serialize_checkpoint(original)
        restored = deserialize_checkpoint(payload)
        self.assertEqual(restored, original)
        self.assertIsInstance(restored.identity, CustomerIdentity)
        self.assertIsInstance(restored.call_brief, CallBrief)
        self.assertIsInstance(restored.retrieved_data, RetrievedContext)
        self.assertIsInstance(restored.messages[0], Message)
        restored.working_memory["pending_order"]["quantity"] = 9
        self.assertEqual(original.working_memory["pending_order"]["quantity"], 2)
        self.assertEqual(payload["state"]["working_memory"]["pending_order"]["quantity"], 2)

    def test_new_empty_state_can_be_restored(self):
        state = ConversationState(str(uuid4()))
        self.assertEqual(deserialize_checkpoint(serialize_checkpoint(state)), state)

    def test_unknown_version_missing_extra_and_wrong_types_are_rejected(self):
        valid = serialize_checkpoint(example_state(str(uuid4())))
        variants = []
        for version in (True, "1", 2):
            variants.append({**valid, "version": version})
        missing = deepcopy(valid)
        del missing["state"]["working_memory"]
        variants.append(missing)
        extra = deepcopy(valid)
        extra["state"]["identity"]["extra"] = "bad"
        variants.append(extra)
        for turn in ("1", True, -1):
            item = deepcopy(valid)
            item["state"]["turn_number"] = turn
            variants.append(item)
        for value in (None, {}, {**valid, "debug": {}}, *variants):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(CheckpointError):
                deserialize_checkpoint(value)

    def test_binary_nonfinite_and_unsupported_values_are_rejected(self):
        for value in (b"audio", float("nan"), float("inf"), {"set"}):
            state = example_state(str(uuid4()))
            state.working_memory["bad"] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaises(CheckpointError):
                serialize_checkpoint(state)

    def test_size_is_measured_in_utf8_bytes_without_truncation(self):
        state = example_state(str(uuid4()))
        state.working_memory["large"] = "ệ" * 750000
        with self.assertRaises(CheckpointTooLargeError):
            serialize_checkpoint(state)
        self.assertEqual(len(state.working_memory["large"]), 750000)


@contextmanager
def private_schema(database_url: str):
    """Only this generated schema can be removed by the test cleanup."""
    name = "app_data_test_" + uuid4().hex
    admin = create_app_engine(database_url)
    engine = create_app_engine(database_url).execution_options(schema_translate_map={None: name})
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(name))
        created = True

        yield engine
    finally:
        engine.dispose()
        if created:
            assert name.startswith("app_data_test_") and name[14:].isalnum()
            with admin.begin() as connection:
                connection.execute(DropSchema(name, cascade=True))
        admin.dispose()


class AppDataPostgresTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ.get("APP_DATA_TEST_DATABASE_URL")
        if not url:
            raise unittest.SkipTest("Set APP_DATA_TEST_DATABASE_URL to run isolated PostgreSQL tests")
        cls.schema_context = private_schema(url)
        cls.engine = cls.schema_context.__enter__()
        cls.addClassCleanup(cls.schema_context.__exit__, None, None, None)
        Customer.__table__.create(cls.engine)
        with cls.engine.begin() as connection:
            connection.execute(Customer.__table__.insert().values(
                customer_id="TEST001", name="Khách mẫu", phone="0900000000"))
        migrate_app_data(cls.engine)

    async def asyncSetUp(self):
        with self.engine.begin() as connection:
            for table in reversed(APP_TABLES):
                connection.execute(delete(table))
        self.repo = AppDataRepository(self.engine)
        self.user = await self.repo.create_user("Người dùng", " FIRST@example.com ", "$argon2id$test-only")
        self.other = await self.repo.create_user("Khác", "second@example.com", "$argon2id$test-only")
        self.user_id = self.user["id"]

    async def make_turn(self):
        conversation = await self.repo.create_conversation(self.user_id)
        state = example_state(conversation["id"])
        result = await self.repo.save_turn(self.user_id, state, "Xin chào", "Chào bạn", PREVIEW)
        return conversation, state, result

    async def test_migration_repeat_preserves_customer_and_existing_rows(self):
        for _ in range(2):
            self.assertEqual(len(migrate_app_data(self.engine)), 5)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(Customer)), 1)
            self.assertEqual(connection.scalar(select(Customer.name)), "Khách mẫu")
            self.assertEqual(connection.scalar(select(func.count()).select_from(User)), 2)
        schema = self.engine.get_execution_options()["schema_translate_map"][None]
        tables = set(inspect(self.engine).get_table_names(schema=schema))
        self.assertEqual(tables, {"customers", *(table.name for table in APP_TABLES)})

    async def test_migration_empty_schema_fails_without_creating_business_tables(self):
        with private_schema(os.environ["APP_DATA_TEST_DATABASE_URL"]) as engine:
            with self.assertRaisesRegex(ValueError, "customers"):
                migrate_app_data(engine)
            schema = engine.get_execution_options()["schema_translate_map"][None]
            self.assertEqual(inspect(engine).get_table_names(schema=schema), [])

    async def test_duplicate_email_rolls_back_and_normalizes(self):
        self.assertEqual(self.user["email"], "first@example.com")
        self.assertNotIn("password_hash", self.user)
        with self.assertRaises(IntegrityError):
            await self.repo.create_user("Trùng", "First@Example.com", "$argon2id$test-only")
        self.assertEqual((await self.repo.find_user_credentials(" FIRST@example.com "))["id"], self.user_id)
        created = await self.repo.create_user("Sau rollback", "third@example.com", "$argon2id$test-only")
        self.assertNotEqual(created["id"], self.user_id)

    async def test_migration_refuses_incompatible_existing_table_without_partial_changes(self):
        with private_schema(os.environ["APP_DATA_TEST_DATABASE_URL"]) as engine:
            Customer.__table__.create(engine)
            Table("users", MetaData(), Column("id", Uuid, primary_key=True)).create(engine)
            with self.assertRaisesRegex(ValueError, "users"):
                migrate_app_data(engine)
            schema = engine.get_execution_options()["schema_translate_map"][None]
            self.assertEqual(set(inspect(engine).get_table_names(schema=schema)), {"customers", "users"})

    async def test_session_expiry_revoke_and_hash_only(self):
        digest = hashlib.sha256(b"test-session-token").hexdigest()
        await self.repo.create_auth_session(self.user_id, digest, utc_now() + timedelta(days=7))
        self.assertEqual(await self.repo.get_session_user(digest), self.user)
        self.assertIsNone(await self.repo.get_session_user("test-session-token"))
        with self.engine.begin() as connection:
            connection.execute(update(AuthSession).values(expires_at=utc_now() - timedelta(seconds=1)))
        self.assertIsNone(await self.repo.get_session_user(digest))
        await self.repo.delete_auth_session(digest)
        await self.repo.delete_auth_session(digest)
        with self.assertRaises(ValueError):
            await self.repo.create_auth_session(self.user_id, "raw-token", utc_now() + timedelta(days=7))

    async def test_atomic_save_load_and_public_detail(self):
        conversation, state, result = await self.make_turn()
        reloaded = AppDataRepository(self.engine)
        self.assertEqual(await reloaded.load_state(self.user_id, conversation["id"]), state)
        detail = await reloaded.get_conversation(self.user_id, conversation["id"])
        self.assertEqual([message["role"] for message in detail["messages"]], ["user", "agent"])
        self.assertEqual(detail["messages"][1]["id"], result["message_id"])
        self.assertEqual(detail["call_brief"], PREVIEW)
        self.assertNotIn("checkpoint", detail)
        self.assertNotIn("customer_memory", detail)
        self.assertTrue(await reloaded.conversation_exists(conversation["id"]))

    async def test_save_rolls_back_messages_brief_and_checkpoint_on_commit_error(self):
        conversation = await self.repo.create_conversation(self.user_id)
        state = example_state(conversation["id"])

        def fail_commit(_connection):
            raise RuntimeError("simulated commit failure")

        event.listen(self.engine, "commit", fail_commit)
        try:
            with self.assertRaisesRegex(RuntimeError, "simulated"):
                await self.repo.save_turn(self.user_id, state, "Xin chào", "Chào bạn", PREVIEW)
        finally:
            event.remove(self.engine, "commit", fail_commit)
        detail = await self.repo.get_conversation(self.user_id, conversation["id"])
        self.assertEqual(detail["messages"], [])
        self.assertIsNone(detail["call_brief"])
        self.assertEqual((await self.repo.load_state(self.user_id, conversation["id"])).turn_number, 0)
        await self.repo.save_turn(self.user_id, state, "Xin chào", "Chào bạn", PREVIEW)

    async def test_concurrent_same_turn_has_one_success_and_no_duplicates(self):
        conversation = await self.repo.create_conversation(self.user_id)
        state = example_state(conversation["id"])
        results = await asyncio.gather(*(
            self.repo.save_turn(self.user_id, state, "Xin chào", "Chào bạn", PREVIEW) for _ in range(2)
        ), return_exceptions=True)
        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        self.assertEqual(sum(isinstance(item, ConversationConflict) for item in results), 1)
        detail = await self.repo.get_conversation(self.user_id, conversation["id"])
        self.assertEqual(len(detail["messages"]), 2)

    async def test_other_user_cannot_access_modify_or_feedback(self):
        conversation, state, result = await self.make_turn()
        other_id = self.other["id"]
        operations = [
            self.repo.get_conversation(other_id, conversation["id"]),
            self.repo.load_state(other_id, conversation["id"]),
            self.repo.end_conversation(other_id, conversation["id"]),
            self.repo.put_feedback(other_id, result["message_id"], "positive", "bad"),
            self.repo.delete_feedback(other_id, result["message_id"]),
        ]
        state.turn_number = 2
        operations.append(self.repo.save_turn(other_id, state, "Xin chào", "Chào bạn", PREVIEW))
        results = await asyncio.gather(*operations, return_exceptions=True)
        self.assertTrue(all(isinstance(item, AppDataNotFound) for item in results))
        self.assertEqual((await self.repo.list_conversations(other_id))["items"], [])

    async def test_feedback_upsert_concurrent_delete_and_target_validation(self):
        conversation, _, result = await self.make_turn()
        await asyncio.gather(*(
            self.repo.put_feedback(self.user_id, result["message_id"], rating, "  Rõ ràng  ")
            for rating in ("positive", "negative")
        ))
        await self.repo.put_feedback(self.user_id, result["message_id"], None, "  Chỉnh sửa  ")
        detail = await self.repo.get_conversation(self.user_id, conversation["id"])
        self.assertEqual(detail["messages"][1]["feedback"], {"rating": None, "comment": "Chỉnh sửa"})
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(MessageFeedback)), 1)
        with self.assertRaises(AppDataNotFound):
            await self.repo.put_feedback(self.user_id, result["user_message_id"], "positive", "")
        with self.assertRaises(ValueError):
            await self.repo.put_feedback(self.user_id, result["message_id"], "invalid", "")
        with self.assertRaises(ValueError):
            await self.repo.put_feedback(self.user_id, result["message_id"], None, "x" * 1001)
        await self.repo.delete_feedback(self.user_id, result["message_id"])
        await self.repo.delete_feedback(self.user_id, result["message_id"])

    async def test_end_is_idempotent_and_pagination_preserves_order(self):
        conversation, state, _ = await self.make_turn()
        page = await self.repo.get_conversation(self.user_id, conversation["id"], limit=1)
        self.assertTrue(page["has_more"])
        self.assertEqual(page["messages"][0]["role"], "user")
        page = await self.repo.get_conversation(self.user_id, conversation["id"], limit=1, offset=1)
        self.assertFalse(page["has_more"])
        self.assertEqual(page["messages"][0]["role"], "agent")
        await self.repo.end_conversation(self.user_id, conversation["id"])
        await self.repo.end_conversation(self.user_id, conversation["id"])
        state.turn_number = 2
        with self.assertRaises(ConversationConflict):
            await self.repo.save_turn(self.user_id, state, "Xin chào", "Chào bạn", PREVIEW)
        self.assertEqual((await self.repo.get_conversation(self.user_id, conversation["id"]))["status"], "ended")
        with self.assertRaises(ValueError):
            await self.repo.list_conversations(self.user_id, limit=101)

    async def test_db_constraints_reject_invalid_fk_role_and_duplicate_turn(self):
        conversation, _, _ = await self.make_turn()
        for values in (
            {"conversation_id": conversation["id"], "turn_number": 2, "role": "invalid"},
            {"conversation_id": str(uuid4()), "turn_number": 1, "role": "user"},
            {"conversation_id": conversation["id"], "turn_number": 1, "role": "user"},
        ):
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with self.engine.begin() as connection:
                    connection.execute(ChatMessage.__table__.insert().values(content="test", **values))

    async def test_invalid_checkpoint_is_not_silently_reset(self):
        conversation = await self.repo.create_conversation(self.user_id)
        with self.engine.begin() as connection:
            connection.execute(update(Conversation).where(Conversation.id == conversation["id"]).values(
                checkpoint={"version": 99, "state": {}}))
        with self.assertRaises(CheckpointError):
            await self.repo.load_state(self.user_id, conversation["id"])
        self.assertEqual((await self.repo.get_conversation(self.user_id, conversation["id"]))["messages"], [])


if __name__ == "__main__":
    unittest.main()
