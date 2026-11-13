"""Synthetic SQLite API integration; optional PostgreSQL migration tests below."""
import asyncio
from datetime import timedelta
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from telesale_agent.adapters.db.app_models import APP_TABLES, Conversation, utc_now
from telesale_agent.adapters.db.app_repository import AppDataRepository
from telesale_agent.adapters.db.models import Customer
from telesale_agent.adapters.db.voice_store import VoiceStore, metadata, turns
from telesale_agent.core.models import ConversationState, CustomerIdentity, Message
from telesale_agent.entrypoints.api import auth, chat


class DemoHarness:
    """Deterministic external-service substitute; the HTTP/DB save path is real."""
    async def run_turn(self, turn, state, **kwargs):
        if turn.audio:
            turn.text = "Bản ghi âm kiểm thử"
        state.turn_number += 1
        state.identity = CustomerIdentity(phone=turn.customer_hint)
        state.customer_memory = {"facts": {"last_request": turn.text}}
        response = "Đã ghi nhận nhu cầu demo."
        state.messages.extend([Message("user", turn.text), Message("agent", response)])
        from telesale_agent.core.models import CallBrief
        brief = CallBrief(customer_id=None, summary=turn.text, needs=[turn.text])
        state.call_brief = brief
        return SimpleNamespace(state=state, response_text=response, call_brief=brief, latency={})


@compiles(JSONB, "sqlite")
def sqlite_jsonb(_type, compiler, **kw):
    return "JSON"


class SalesmanAPITests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Customer.__table__.create(self.engine)
        for table in APP_TABLES:
            table.create(self.engine)
        metadata.create_all(self.engine)
        self.repository = AppDataRepository(self.engine)
        self.store = VoiceStore(self.engine)
        self.environment = patch.dict(os.environ, {"WEB_ORIGIN": "http://testserver", "API_KEY": "", "SESSION_COOKIE_SECURE": "false", "ENABLE_DEBUG_RESPONSE": "false"})
        self.environment.start()
        chat.app.dependency_overrides[auth.get_auth_repository] = lambda: self.repository
        self.client = TestClient(chat.app)  # No lifespan: never connect real MCP/LLM.
        self.client.headers["Origin"] = "http://testserver"
        self.addCleanup(self.client.close)
        self.addCleanup(chat.app.dependency_overrides.clear)
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.engine.dispose)
        self.users = {}
        for name, email, role in (("Nguyễn Ánh", "a@example.invalid", "user"), ("User B", "b@example.invalid", "user"),
                                  ("Sales", "sales@example.invalid", "salesman")):
            response = self.client.post("/api/auth/register", json={"name": name, "email": email, "password": "Demo2026", "role": role})
            self.assertEqual(response.status_code, 201, response.text)
            self.users[role if role == "salesman" else email[0]] = response.json()["user"]

    def login(self, key="salesman"):
        user = self.users[key]
        response = self.client.post("/api/auth/login", json={"email": user["email"], "password": "Demo2026"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["role"], user["role"])
        return response

    def conversation(self, owner="a", content="Xin chào", memory=None):
        row = asyncio.run(self.repository.create_conversation(self.users[owner]["id"]))
        state = ConversationState(row["id"], turn_number=1, identity=CustomerIdentity(phone="0900000000"),
                                  customer_memory=memory or {"facts": {"budget_vnd": 3000000}},
                                  messages=[Message("user", content), Message("agent", "Chào bạn")])
        asyncio.run(self.repository.save_turn(self.users[owner]["id"], state, content, "Chào bạn", {
            "summary": "Tư vấn", "needs": [], "objections": [], "unresolved_issues": [],
        }))
        return row["id"]

    def voice(self, number, *, interrupted=False, snapshot=True, legacy=False):
        payload = {"conversation_id": "live-demo", "phone": "0900000000", "input_text": f"Khách lượt {number}",
                   "output_text": f"Agent lượt {number}", "input_finished": not interrupted, "interrupted": interrupted}
        if not legacy:
            payload.update(user_id=self.users["b"]["id"], turn_number=number, created_at=f"2026-11-13T03:00:0{number}+00:00")
        source = f"voice:live-demo:{number}"
        asyncio.run(self.store.save(source, None, payload, status="incomplete" if interrupted else "pending"))
        if snapshot:
            asyncio.run(self.store.save_snapshot(source, {"summary": f"Brief {number}"}, {"customer_memory": {"facts": {"number": number}}}))
        return source

    def test_auth_defaults_validation_and_logout(self):
        response = self.client.post("/api/auth/register", json={"name": "Old client", "email": "old@example.invalid", "password": "Demo2026"})
        self.assertEqual(response.json()["user"]["role"], "user")
        for role in ("admin", None, 1, "Salesman"):
            response = self.client.post("/api/auth/register", json={"name": "Invalid", "email": "bad@example.invalid", "password": "Demo2026", "role": role})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("Demo2026", response.text)
        self.login()
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["role"], "salesman")
        self.assertNotIn("password", self.client.get("/api/auth/me").text)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_role_matrix_and_ownership(self):
        identifier = self.conversation()
        self.assertEqual(self.client.get("/api/salesman/conversations").status_code, 401)
        self.login("b")
        self.assertEqual(self.client.get("/api/salesman/conversations").status_code, 403)
        self.assertEqual(self.client.get(f"/api/conversations/{identifier}").status_code, 404)
        self.login()
        response = self.client.get(f"/api/salesman/conversations/chat/{identifier}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.json()["user"]["id"], self.users["a"]["id"])

    def test_readonly_guards_run_before_agent_and_voice_bootstrap(self):
        self.login()
        harness = SimpleNamespace(run_turn=AsyncMock())
        with patch.object(chat, "harness", harness):
            for accept in ("application/json", "text/event-stream"):
                response = self.client.post("/api/chat", json={"conversation_id": str(uuid4()), "message": "Hello"}, headers={"Accept": accept})
                self.assertEqual(response.status_code, 403, response.text)
            response = self.client.post("/api/chat/audio", data={"conversation_id": str(uuid4())}, files={"file": ("demo.wav", b"audio", "audio/wav")})
            self.assertEqual(response.status_code, 403, response.text)
            harness.run_turn.assert_not_awaited()
        for method, path, body in (("POST", "/api/conversations", {}), ("POST", f"/api/conversations/{uuid4()}/end", None),
                                   ("PUT", f"/api/messages/{uuid4()}/feedback", {"rating": "positive"}),
                                   ("DELETE", f"/api/messages/{uuid4()}/feedback", None),
                                   ("DELETE", "/api/sessions/guest-example", None),
                                   ("POST", "/api/voice/sessions", {})):
            response = self.client.request(method, path, json=body)
            self.assertEqual(response.status_code, 403, (path, response.text))

    def test_expired_account_cannot_downgrade_to_guest(self):
        self.client.cookies.set(auth.COOKIE_NAME, "bad-cookie")
        for path in ("/api/chat", "/api/voice/sessions"):
            body = {"conversation_id": "guest", "message": "Hi"} if path.endswith("chat") else {}
            self.assertEqual(self.client.post(path, json=body).status_code, 401)

    def test_text_and_upload_saved_through_http_are_visible_to_salesman(self):
        self.login("a")
        identifier = self.client.post("/api/conversations", json={}).json()["id"]
        with patch.object(chat, "harness", DemoHarness()), patch.object(chat.provider_cooldown, "remaining", return_value=0):
            response = self.client.post("/api/chat", json={"conversation_id": identifier, "message": "Tôi cần máy lọc", "customer_phone": "0900000000"}, headers={"X-Conversation-Mode": "account"})
            self.assertEqual(response.status_code, 200, response.text)
            response = self.client.post("/api/chat/audio", data={"conversation_id": identifier}, files={"file": ("demo.wav", b"synthetic", "audio/wav")}, headers={"X-Conversation-Mode": "account"})
            self.assertEqual(response.status_code, 200, response.text)
        self.client.post("/api/auth/logout")
        self.login()
        data = self.client.get(f"/api/salesman/conversations/chat/{identifier}").json()
        self.assertEqual(len(data["messages"]), 4)
        self.assertEqual(data["messages"][0]["content"], "Tôi cần máy lọc")
        self.assertEqual(data["messages"][2]["content"], "Bản ghi âm kiểm thử")
        self.assertEqual(data["turn_number"], 2)

    def test_account_voice_binds_owner_and_guest_still_requires_access_code(self):
        from fastapi import FastAPI
        from telesale_agent.entrypoints.api.voice import create_voice_router
        manager = SimpleNamespace(create=AsyncMock(return_value={"session_id": "synthetic"}))
        app = FastAPI()
        router, _ = create_voice_router(lambda: object(), manager_factory=lambda *_: manager)
        app.include_router(router)
        app.dependency_overrides[auth.get_auth_repository] = lambda: self.repository
        self.login("a")
        with TestClient(app) as client, patch.dict(os.environ, {"REALTIME_VOICE_ENABLED": "true", "API_KEY": "guest-key"}), patch(
                "telesale_agent.entrypoints.api.voice.ConversationServices.from_harness", return_value=object()):
            self.assertEqual(client.post("/api/voice/sessions", json={}).status_code, 401)
            client.cookies.update(self.client.cookies)
            result = client.post("/api/voice/sessions", json={}, headers={"Origin": "http://testserver", "X-Conversation-Mode": "account"})
            self.assertEqual(result.status_code, 200, result.text)
            manager.create.assert_awaited_once_with(None, user_id=self.users["a"]["id"])

    def test_search_combined_sources_pagination_and_empty_detail(self):
        self.conversation("a")
        self.conversation("b")
        empty = asyncio.run(self.repository.create_conversation(self.users["a"]["id"]))
        self.voice(1)
        self.voice(2)
        self.login()
        page = self.client.get("/api/salesman/conversations?limit=2").json()
        self.assertEqual(page["total"], 4)
        self.assertTrue(page["has_more"])
        second = self.client.get("/api/salesman/conversations?limit=2&offset=2").json()
        keys = [(item["source"], item["id"]) for item in page["items"] + second["items"]]
        self.assertEqual(len(set(keys)), 4)
        self.assertEqual(self.client.get("/api/salesman/conversations?q=nguyen%20anh").json()["total"], 2)
        self.assertEqual(self.client.get("/api/salesman/conversations?source=voice").json()["total"], 1)
        self.assertEqual(self.client.get("/api/salesman/conversations?q=%25").json()["total"], 0)
        result = self.client.get(f"/api/salesman/conversations/chat/{empty['id']}").json()
        self.assertEqual(result["messages"], [])

    def test_transcript_projection_missing_snapshot_and_readonly_get(self):
        identifier = self.conversation(memory={"facts": {"budget_vnd": 3000000, "api_key": "SECRET"}, "password_hash": "SECRET"})
        self.login()
        with patch.object(chat, "harness", SimpleNamespace(run_turn=AsyncMock())):
            response = self.client.get(f"/api/salesman/conversations/chat/{identifier}?limit=1")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["messages"][0]["role"], "user")
            self.assertTrue(data["has_more"])
            next_page = self.client.get(f"/api/salesman/conversations/chat/{identifier}?limit=1&offset={data['next_offset']}").json()
            self.assertEqual(next_page["messages"][0]["role"], "agent")
            self.assertEqual(data["memory"]["customer_memory"]["facts"]["budget_vnd"], 3000000)
            self.assertNotIn("SECRET", response.text)
            self.assertNotIn("checkpoint", data)
            chat.harness.run_turn.assert_not_awaited()
        with self.engine.begin() as connection:
            connection.execute(update(Conversation).where(Conversation.id == identifier).values(checkpoint={"version": 99}))
        data = self.client.get(f"/api/salesman/conversations/chat/{identifier}").json()
        self.assertIsNone(data["memory"])
        self.assertEqual(len(data["messages"]), 2)

    def test_voice_sequence_latest_completed_snapshot_legacy_and_preserved_job(self):
        first = self.voice(1)
        self.voice(3, interrupted=True, snapshot=False)
        self.voice(2)
        asyncio.run(self.store.prepared(first, {"operations": [], "writes": []}))
        asyncio.run(self.store.save_snapshot(first, {"summary": "Older finalized late"}, {"customer_memory": {"facts": {"number": 1}}}))
        job = asyncio.run(self.store.get(first))
        self.assertEqual(job["status"], "prepared")
        self.assertIsNotNone(job["prepared"])
        self.login()
        data = self.client.get("/api/salesman/conversations/voice/live-demo").json()
        self.assertEqual([message["content"] for message in data["messages"]][::2], ["Khách lượt 1", "Khách lượt 2", "Khách lượt 3"])
        self.assertEqual(data["call_brief"]["summary"], "Brief 2")
        self.assertEqual(data["memory"]["customer_memory"]["facts"]["number"], 2)
        self.assertTrue(data["messages"][-1]["incomplete"])
        self.assertEqual(data["user"]["id"], self.users["b"]["id"])
        self.voice(4, legacy=True, snapshot=False)
        self.assertEqual(self.client.get("/api/salesman/conversations/voice/live-demo").status_code, 200)

    def test_validation_missing_voice_table_and_database_failure(self):
        self.login()
        for suffix in ("?limit=0", "?offset=-1", "?source=other", "/other/x", "/chat/bad-id"):
            self.assertEqual(self.client.get("/api/salesman/conversations" + suffix).status_code, 422, suffix)
        self.assertEqual(self.client.get(f"/api/salesman/conversations/chat/{uuid4()}").status_code, 404)
        self.assertEqual(self.client.get("/api/salesman/conversations/voice/missing").status_code, 404)
        turns.drop(self.engine)
        self.assertEqual(self.client.get("/api/salesman/conversations").json()["items"], [])
        from sqlalchemy.exc import OperationalError
        from telesale_agent.adapters.db.salesman_repository import SalesmanRepository
        with patch.object(SalesmanRepository, "list", AsyncMock(side_effect=OperationalError("query", {}, Exception("SECRET")))):
            response = self.client.get("/api/salesman/conversations")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SECRET", response.text)


class SalesmanMigrationPostgresTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("APP_DATA_TEST_DATABASE_URL"), "Set APP_DATA_TEST_DATABASE_URL for PostgreSQL migration")
    def test_upgrade_legacy_users_and_repeat_preserves_sessions(self):
        from test_app_data import private_schema
        from telesale_agent.adapters.db.app_schema import migrate_app_data
        with private_schema(os.environ["APP_DATA_TEST_DATABASE_URL"]) as engine:
            Customer.__table__.create(engine)
            migrate_app_data(engine)
            schema = engine.get_execution_options()["schema_translate_map"][None]
            table = engine.dialect.identifier_preparer.quote(schema) + ".users"
            repository = AppDataRepository(engine)
            user = asyncio.run(repository.create_user("Legacy", "legacy@example.invalid", "hash"))
            asyncio.run(repository.create_auth_session(user["id"], "a" * 64, utc_now() + timedelta(days=1)))
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {table} DROP COLUMN role"))
            migrate_app_data(engine)
            migrate_app_data(engine)
            restored = asyncio.run(repository.get_session_user("a" * 64))
            self.assertEqual(restored["role"], "user")
            self.assertEqual(restored["id"], user["id"])


if __name__ == "__main__":
    unittest.main()
