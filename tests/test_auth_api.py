"""Auth API tests against PostgreSQL in a disposable schema; no browser/LLM."""

import os
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import OperationalError

from test_app_data import private_schema
from telesale_agent.adapters.db.app_models import APP_TABLES, AuthSession, User, utc_now
from telesale_agent.adapters.db.app_repository import AppDataRepository
from telesale_agent.adapters.db.app_schema import migrate_app_data
from telesale_agent.adapters.db.models import Customer
from telesale_agent.entrypoints.api import auth

PASSWORD = "Demo2026"
ORIGIN = "http://localhost:3000"


class AuthAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ.get("APP_DATA_TEST_DATABASE_URL")
        if not url:
            raise unittest.SkipTest("Set APP_DATA_TEST_DATABASE_URL to run isolated PostgreSQL auth API tests")
        cls.schema_context = private_schema(url)
        cls.engine = cls.schema_context.__enter__()
        cls.addClassCleanup(cls.schema_context.__exit__, None, None, None)
        Customer.__table__.create(cls.engine)
        migrate_app_data(cls.engine)

    def setUp(self):
        with self.engine.begin() as connection:
            for table in reversed(APP_TABLES):
                connection.execute(delete(table))
        self.environment = patch.dict(os.environ, {"WEB_ORIGIN": ORIGIN, "SESSION_TTL_DAYS": "7"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.repository = AppDataRepository(self.engine)
        self.app = FastAPI()
        self.app.include_router(auth.router)
        self.app.dependency_overrides[auth.get_auth_repository] = lambda: self.repository
        self.client = TestClient(self.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
        self.addCleanup(self.client.close)

    def register(self, email="first@example.com", name="Người dùng thử"):
        return self.client.post("/api/auth/register", json={"name": name, "email": email, "password": PASSWORD})

    def login(self, email="first@example.com", password=PASSWORD):
        return self.client.post("/api/auth/login", json={"email": email, "password": password})

    def test_register_persists_normalized_email_and_argon2_hash_without_session(self):
        response = self.register(" FIRST@Example.com ")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json()["user"]["email"], "first@example.com")
        self.assertNotIn("password", response.text)
        self.assertNotIn("set-cookie", response.headers)
        with self.engine.connect() as connection:
            row = connection.execute(select(User.__table__)).mappings().one()
            self.assertTrue(row["password_hash"].startswith("$argon2id$"))
            self.assertNotEqual(row["password_hash"], PASSWORD)
            self.assertTrue(auth.passwords.verify(PASSWORD, row["password_hash"]))
            self.assertEqual(connection.scalar(select(func.count()).select_from(AuthSession)), 0)

    def test_duplicate_email_returns_409_and_keeps_one_user(self):
        self.assertEqual(self.register().status_code, 201)
        duplicate = self.register(" FIRST@Example.com ")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.headers["cache-control"], "no-store")
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(User)), 1)

    def test_login_me_and_logout_revoke_the_stored_token_hash(self):
        user = self.register().json()["user"]
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"user": user})
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie)
        self.assertIn("Path=/", cookie)
        self.assertIn("Max-Age=604800", cookie)
        self.assertNotIn("Domain=", cookie)
        self.assertNotIn("Secure", cookie)
        token = self.client.cookies[auth.COOKIE_NAME]
        with self.engine.connect() as connection:
            row = connection.execute(select(AuthSession.__table__)).mappings().one()
            self.assertEqual(row["token_hash"], auth.token_hash(token))
            self.assertNotEqual(row["token_hash"], token)
            self.assertAlmostEqual((row["expires_at"] - utc_now()).total_seconds(), 604800, delta=10)
        self.assertEqual(self.client.get("/api/auth/me").json(), {"user": user})
        self.assertEqual(self.client.get("/api/auth/me").headers["cache-control"], "no-store")
        response = self.client.post("/api/auth/logout")
        self.assertEqual(response.json(), {"status": "logged_out"})
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(AuthSession)), 0)

    def test_unknown_email_and_wrong_password_have_same_401_response(self):
        self.register()
        unknown = self.login("missing@example.com")
        wrong = self.login(password="incorrect-password")
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.json(), wrong.json())
        self.assertNotIn(PASSWORD, unknown.text)
        self.assertNotIn("set-cookie", wrong.headers)

    def test_expired_unknown_and_malformed_cookies_are_rejected(self):
        self.register()
        self.login()
        with self.engine.begin() as connection:
            connection.execute(update(AuthSession).values(expires_at=utc_now() - timedelta(seconds=1)))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        for token in ("invalid", "a" * 43):
            self.client.cookies.clear()
            self.client.cookies.set(auth.COOKIE_NAME, token)
            response = self.client.get("/api/auth/me")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_login_rotates_old_session_and_switches_user(self):
        self.register()
        other = self.register("second@example.com", "Người dùng khác").json()["user"]
        self.login()
        old_token = self.client.cookies[auth.COOKIE_NAME]
        self.assertEqual(self.login("second@example.com").status_code, 200)
        self.assertNotEqual(self.client.cookies[auth.COOKIE_NAME], old_token)
        self.assertEqual(self.client.get("/api/auth/me").json()["user"], other)
        with TestClient(self.app, base_url=ORIGIN) as old_client:
            old_client.cookies.set(auth.COOKIE_NAME, old_token)
            self.assertEqual(old_client.get("/api/auth/me").status_code, 401)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(AuthSession)), 1)

    def test_missing_or_foreign_origin_cannot_register_login_or_logout(self):
        self.register()
        self.login()
        self.assertEqual(self.client.get("/api/auth/me", headers={"Origin": "https://evil.test"}).status_code, 403)
        for origin in (None, "null", "http://localhost:3000.evil.test", "https://evil.test"):
            with TestClient(self.app, base_url=ORIGIN) as client:
                headers = {} if origin is None else {"Origin": origin}
                for path in ("register", "login", "logout"):
                    response = client.post("/api/auth/" + path, headers=headers, json={})
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.headers["cache-control"], "no-store")

    def test_invalid_inputs_never_echo_passwords_or_write_users(self):
        invalid = [
            {"name": "A", "email": "first@example.com", "password": PASSWORD},
            {"name": "Valid name", "email": "invalid", "password": PASSWORD},
            {"name": "Valid name", "email": "first@example.com", "password": "short12"},
            {"name": "Valid name", "email": "first@example.com", "password": "x" * 129},
            {"name": "Valid name", "email": "first@example.com", "password": PASSWORD, "role": "admin"},
            {"name": "Valid name", "email": "first@example.com", "password": {"secret": PASSWORD}},
            [], None,
        ]
        for body in invalid:
            response = self.client.post("/api/auth/register", json=body)
            self.assertIn(response.status_code, (415, 422))
            self.assertNotIn(PASSWORD, response.text)
            self.assertNotIn("short12", response.text)
        response = self.client.post("/api/auth/login", content="{invalid", headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)
        response = self.client.post("/api/auth/login", data={"email": "first@example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, 415)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(User)), 0)

    def test_https_configuration_sets_secure_host_only_cookie(self):
        self.register()
        with patch.dict(os.environ, {"WEB_ORIGIN": "https://web.example.test"}):
            with TestClient(self.app, base_url="https://web.example.test", headers={"Origin": "https://web.example.test"}) as client:
                response = client.post("/api/auth/login", json={"email": "first@example.com", "password": PASSWORD})
                self.assertEqual(response.status_code, 200)
                self.assertIn("Secure", response.headers["set-cookie"])
                self.assertNotIn("Domain=", response.headers["set-cookie"])
                self.assertEqual(client.get("/api/auth/me").status_code, 200)
                self.assertEqual(client.post("/api/auth/logout").status_code, 200)

    def test_database_error_returns_503_without_sql_or_secret(self):
        failing = AsyncMock()
        failing.find_user_credentials.side_effect = OperationalError("secret-sql", {}, Exception("private-db-detail"))
        self.app.dependency_overrides[auth.get_auth_repository] = lambda: failing
        response = self.login()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret-sql", response.text)
        self.assertNotIn("private-db-detail", response.text)
        self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_invalid_session_ttl_is_rejected_before_creating_a_session(self):
        for ttl in ("0", "-1", "invalid", "999999999999999"):
            with self.subTest(ttl=ttl), patch.dict(os.environ, {"SESSION_TTL_DAYS": ttl}):
                response = self.login()
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("set-cookie", response.headers)
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(AuthSession)), 0)

    def test_router_is_mounted_in_main_app(self):
        from telesale_agent.entrypoints.api.chat import app
        paths = set(app.openapi()["paths"])
        self.assertTrue({"/api/auth/register", "/api/auth/login", "/api/auth/me", "/api/auth/logout"}.issubset(paths))
        client = TestClient(app)
        try:
            self.assertEqual(client.get("/api/auth/me").status_code, 401)
        finally:
            client.close()

    def test_web_clients_through_http_and_database(self):
        """Run the frontend's real request clients without a browser or external LLM."""
        import io
        import shutil
        import socket
        import subprocess
        import threading
        import time
        from pathlib import Path
        from contextlib import redirect_stdout
        from types import SimpleNamespace

        import uvicorn
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        from langgraph.graph import END, START, MessagesState, StateGraph
        from telesale_agent.application.deepagent.harness import DeepAgentHarness
        from telesale_agent.application.memory.call_brief import CallBriefProjector
        from telesale_agent.core.models import ActionPlan, CustomerIdentity, Perception, PolicyDecision
        from telesale_agent.entrypoints.api import chat

        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required to exercise frontend API clients")
        from telesale_agent.adapters.db.models import InventoryEvent, Product, ProductVariant
        from telesale_agent.entrypoints.api import catalog
        for table in (Product.__table__, ProductVariant.__table__, InventoryEvent.__table__):
            table.create(self.engine, checkfirst=True)
        with self.engine.begin() as connection:
            connection.execute(Product.__table__.insert().values(
                sku="SKU-AP-X", name="Máy lọc không khí AirPure X", brand="AirPure",
                category="gia-dung/may-loc-khong-khi", list_price_vnd=1234567, stock=5, attributes={}))
        async def perceive(context):
            deltas = {"budget_vnd": 3000000} if "3000000" in context.input.text else {}
            return Perception(transcript=context.input.text, memory_deltas=deltas)
        harness = DeepAgentHarness(
            identity=SimpleNamespace(resolve_identity=AsyncMock(return_value=CustomerIdentity(phone="0900000000"))),
            perceive=SimpleNamespace(perceive=perceive), call_brief=CallBriefProjector(),
            asr=SimpleNamespace(transcribe=AsyncMock(return_value="Hello from audio")),
        )
        model = FakeListChatModel(responses=["Draft answer"], sleep=0.002)
        async def model_node(state):
            return {"messages": [await model.ainvoke(state["messages"])]}
        graph = StateGraph(MessagesState)
        graph.add_node("model", model_node)
        graph.add_edge(START, "model")
        graph.add_edge("model", END)
        harness.agent = graph.compile()
        harness.guardrail = SimpleNamespace(check=AsyncMock(return_value=PolicyDecision(
            allowed=True, safe_plan=ActionPlan(action="respond_to_customer", rationale="test", response_text="Final verified answer: SKU-AP-X"),
        )))
        previous_override = chat.app.dependency_overrides.get(auth.get_auth_repository)
        chat.app.dependency_overrides[auth.get_auth_repository] = lambda: self.repository
        self.addCleanup(lambda: chat.app.dependency_overrides.pop(auth.get_auth_repository, None)
                        if previous_override is None else chat.app.dependency_overrides.update({auth.get_auth_repository: previous_override}))
        server = uvicorn.Server(uvicorn.Config(chat.app, lifespan="off", log_level="error"))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            with redirect_stdout(io.StringIO()), patch.object(catalog, "db_client", SimpleNamespace(get_session=self.repository.sessions)), patch.object(chat, "harness", harness), patch.object(chat.provider_cooldown, "remaining", return_value=0), patch.dict(os.environ, {
                "API_KEY": "demo-service-key", "SESSION_COOKIE_SECURE": "false", "ENABLE_DEBUG_RESPONSE": "false",
            }):
                thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
                thread.start()
                try:
                    deadline = time.monotonic() + 10
                    while not server.started and thread.is_alive() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertTrue(server.started, "HTTP fixture did not start")
                    root = Path(__file__).resolve().parents[1]
                    result = subprocess.run(
                        [node, "--experimental-transform-types", str(root / "src/web/tests/account-api-flow.mjs")],
                        cwd=root, env={**os.environ, "ACCOUNT_FLOW_API": f"http://127.0.0.1:{port}"},
                        capture_output=True, text=True, encoding="utf-8", timeout=90,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                finally:
                    server.should_exit = True
                    thread.join(timeout=10)
                    self.assertFalse(thread.is_alive(), "HTTP fixture did not stop")

    def test_stream_save_failure_has_no_completion_receipt(self):
        from types import SimpleNamespace
        from telesale_agent.core.models import Message
        from telesale_agent.entrypoints.api import chat

        async def run(turn, state, *, on_text, on_status=None):
            await on_text("Draft reply")
            state.turn_number += 1
            state.messages.extend([Message("customer", turn.text), Message("agent", "Verified reply")])
            return SimpleNamespace(state=state, response_text="Verified reply", call_brief=None, latency={})

        previous_override = chat.app.dependency_overrides.get(auth.get_auth_repository)
        chat.app.dependency_overrides[auth.get_auth_repository] = lambda: self.repository
        self.addCleanup(lambda: chat.app.dependency_overrides.pop(auth.get_auth_repository, None)
                        if previous_override is None else chat.app.dependency_overrides.update({auth.get_auth_repository: previous_override}))
        self.client = TestClient(chat.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
        self.addCleanup(self.client.close)
        self.register()
        self.login()
        key = self.client.post("/api/conversations", json={}).json()["id"]
        with patch.object(chat, "harness", SimpleNamespace(run_turn=run)), patch.object(chat.provider_cooldown, "remaining", return_value=0), patch.object(self.repository, "save_turn", AsyncMock(side_effect=RuntimeError("DB unavailable"))), patch.dict(os.environ, {"ENABLE_DEBUG_RESPONSE": "false"}):
            response = self.client.post("/api/chat", headers={"Accept": "text/event-stream"}, json={"conversation_id": key, "message": "Hello"})
        self.assertIn("event: text", response.text)
        self.assertIn("event: error", response.text)
        self.assertIn("turn_outcome_unknown", response.text)
        self.assertNotIn("event: done", response.text)
        self.assertEqual(self.client.get(f"/api/conversations/{key}").json()["messages"], [])

    def test_conversation_feedback_happy_path(self):
        """Showcase: login, text/audio, brief, history, resume, feedback, end."""
        from types import SimpleNamespace
        from telesale_agent.core.models import CallBrief, CustomerIdentity, Message
        from telesale_agent.entrypoints.api import chat

        async def run(turn, state):
            if turn.audio:
                turn.text = "Nhu cầu từ ghi âm"
            state.turn_number += 1
            state.identity = CustomerIdentity(phone=turn.customer_hint)
            state.working_memory["demo_turns"] = state.turn_number
            answer = f"Đã tư vấn lượt {state.turn_number}"
            state.messages.extend([Message("customer", turn.text), Message("agent", answer)])
            state.call_brief = CallBrief(customer_id=None, summary=answer, needs=[turn.text])
            return SimpleNamespace(state=state, response_text=answer, call_brief=state.call_brief,
                                   latency={}, perception=None, retrieved=None, tool_calls=[], memory_writes=[], usage={})

        previous_override = chat.app.dependency_overrides.get(auth.get_auth_repository)
        chat.app.dependency_overrides[auth.get_auth_repository] = lambda: self.repository
        self.addCleanup(lambda: chat.app.dependency_overrides.pop(auth.get_auth_repository, None)
                        if previous_override is None else chat.app.dependency_overrides.update({auth.get_auth_repository: previous_override}))
        self.client = TestClient(chat.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
        self.addCleanup(self.client.close)
        with patch.object(chat, "harness", SimpleNamespace(run_turn=run)), patch.object(chat.provider_cooldown, "remaining", return_value=0), patch.dict(os.environ, {"API_KEY": "demo-service-key", "ENABLE_DEBUG_RESPONSE": "false"}):
            self.assertEqual(self.register().status_code, 201)
            self.assertEqual(self.login().status_code, 200)
            created = self.client.post("/api/conversations", json={"customer_phone": "0900000000"})
            self.assertEqual(created.status_code, 201)
            key = created.json()["id"]
            first = self.client.post("/api/chat", json={"conversation_id": key, "message": "Tư vấn máy lọc", "customer_phone": "0900000000"})
            self.assertEqual(first.status_code, 200, first.text)
            message_id = first.json()["message_id"]
            self.assertEqual(first.json()["turn_number"], 1)
            self.assertEqual(len(self.client.get("/api/conversations").json()["items"]), 1)
            feedback = {"rating": "positive", "comment": "Tư vấn dễ hiểu"}
            self.assertEqual(self.client.put(f"/api/messages/{message_id}/feedback", json=feedback).status_code, 200)
            detail = self.client.get(f"/api/conversations/{key}").json()
            self.assertEqual([message["role"] for message in detail["messages"]], ["user", "agent"])
            self.assertEqual(detail["messages"][1]["feedback"], feedback)
            self.assertEqual(detail["call_brief"]["summary"], "Đã tư vấn lượt 1")
            # Simulate restarting the process cache/repository; next turn must read PostgreSQL.
            chat.sessions.pop(key, None)
            self.repository = AppDataRepository(self.engine)
            audio = self.client.post("/api/chat/audio", data={"conversation_id": key, "customer_phone": "0900000000"}, files={"file": ("demo.wav", b"synthetic-audio", "audio/wav")})
            self.assertEqual(audio.status_code, 200, audio.text)
            self.assertEqual(audio.json()["turn_number"], 2)
            self.assertEqual(audio.json()["transcript"], "Nhu cầu từ ghi âm")
            detail = self.client.get(f"/api/conversations/{key}").json()
            self.assertEqual(len(detail["messages"]), 4)
            self.assertEqual(detail["call_brief"]["summary"], "Đã tư vấn lượt 2")
            self.assertEqual(self.client.delete(f"/api/messages/{message_id}/feedback").status_code, 200)
            self.assertIsNone(self.client.get(f"/api/conversations/{key}").json()["messages"][1]["feedback"])
            self.assertEqual(self.client.post(f"/api/conversations/{key}/end").json(), {"status": "ended"})
            self.assertEqual(self.client.get(f"/api/conversations/{key}").json()["status"], "ended")
            self.assertNotEqual(self.client.post("/api/conversations", json={}).json()["id"], key)


if __name__ == "__main__":
    unittest.main()
