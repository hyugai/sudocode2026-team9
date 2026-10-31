"""Realtime regression suite: fake model/tools, isolated SQLite and customer memory."""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from telesale_agent.adapters.db.voice_store import VoiceStore, metadata
from telesale_agent.adapters.memory.in_memory import InMemoryCustomerMemoryRepository
from telesale_agent.adapters.memory.turn_persist import TurnMemoryPersister
from telesale_agent.adapters.llm.llm_persist import LLMPersister, EpisodeSummarySchema
from telesale_agent.application.customer_context import CustomerContextService
from telesale_agent.application.memory.call_brief import CallBriefProjector
from telesale_agent.application.memory.coordinator import commit_voice, persist_shared
from telesale_agent.application.realtime.controller import VoiceSessionController, initialize_customer, recover_memory
from telesale_agent.application.realtime.context import brief_data, tool_declarations, public_data
from telesale_agent.application.realtime.session import VoiceSessionManager
from telesale_agent.application.realtime.tool_dispatch import dispatch
from telesale_agent.core.models import (
    CallBrief, Channel, ConversationState, CustomerIdentity, Perception, TurnContext, TurnInput,
)
from telesale_agent.config.realtime import RealtimeSettings
from telesale_agent.adapters.llm.gemini_live import GeminiLiveClient


def services():
    memory = InMemoryCustomerMemoryRepository()
    async def perceive(ctx):
        return Perception(transcript=ctx.input.text, intent="ask_product",
                          memory_deltas={"preference": "màu xanh"})
    async def identity(ctx):
        return CustomerIdentity(customer_id="customer-test", phone=ctx.input.customer_hint)
    crm = SimpleNamespace(retrieve_profile=AsyncMock(return_value={"name": "Khách thử"}),
                          precompute_brief=AsyncMock(return_value={}))
    return SimpleNamespace(
        memory=memory, persist=TurnMemoryPersister(memory), perceive=SimpleNamespace(perceive=perceive),
        identity=SimpleNamespace(resolve_identity=identity), retrieve=None,
        customer_context=CustomerContextService(crm, memory), call_brief=CallBriefProjector(),
        guardrail=None, mcp_tools={})


def context(svc, source="voice:test:turn"):
    identity = CustomerIdentity(customer_id="customer-test")
    state = ConversationState(conversation_id="voice-test", identity=identity,
                              customer_memory=svc.memory.load(identity.customer_id),
                              memory_deltas={"preference": "màu xanh"})
    return TurnContext(input=TurnInput(conversation_id=state.conversation_id, channel=Channel.VOICE,
                                      text="Tôi thích màu xanh", metadata={"memory_source_id": source}),
                       state=state, identity=identity)


class RealtimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        metadata.create_all(self.engine)
        self.store = VoiceStore(self.engine)
        self.svc = services()

    async def asyncTearDown(self):
        self.engine.dispose()

    async def make_controller(self):
        state, initial = await initialize_customer(self.svc, "live-test", "0900000000")
        model = SimpleNamespace(tool_result=AsyncMock(), close=AsyncMock())
        return VoiceSessionController(self.svc, RealtimeSettings(), model, self.store, state, initial, "0900000000")

    async def test_text_runtime_bootstraps_from_shared_mcp_registry(self):
        from telesale_agent.application.deepagent import runtime
        registry = {"search_catalog": object(), "search_policy": object()}
        harness = SimpleNamespace(agent=None, memory=self.svc.memory, exit_stack=object(),
                                  checkpointer=None, _prewarm_knowledge_mcp=AsyncMock())
        compiled_agent = object()
        instruction_dir = Path(__file__).resolve().parents[1] / "data/memory-root/agents/telesales_agent"
        with patch.dict("os.environ", {"AGENT_INSTRUCTIONS_ROOT": str(instruction_dir)}), patch(
                "telesale_agent.adapters.mcp.runtime.connect_tools", new_callable=AsyncMock,
                return_value=registry) as connect, patch.object(
                runtime, "resolve_model_config", return_value=SimpleNamespace(provider="gemini")), patch.object(
                runtime, "create_deepagent_model", return_value=object()), patch.object(
                runtime, "model_provider_key", return_value="gemini"), patch.object(
                runtime, "register_harness_profile"), patch.object(
                runtime, "create_deep_agent", return_value=compiled_agent) as build_agent:
            self.assertIs(await runtime.initialize_runtime(harness), harness)
            self.assertIs(harness.mcp_tools, registry)
            self.assertEqual(build_agent.call_args.kwargs["tools"], list(registry.values()))
            self.assertIs(harness.agent, compiled_agent)
            # An initialized harness must reuse the same connection and graph.
            await runtime.initialize_runtime(harness)
            connect.assert_awaited_once_with(harness.exit_stack, harness.memory)
            harness._prewarm_knowledge_mcp.assert_awaited_once()
            build_agent.assert_called_once()

    async def test_one_event_preserves_audio_and_both_transcripts(self):
        controller = await self.make_controller()
        await controller.provider_event({"server_content": {
            "input_transcription": {"text": "tôi thích màu xanh", "finished": True},
            "output_transcription": {"text": "Em đã hiểu."},
            "model_turn": {"parts": [{"inline_data": {"data": b"\0\0" * 10}}]},
            "turn_complete": True,
        }})
        record = controller.current
        await asyncio.gather(*list(controller.jobs))
        self.assertTrue(record.finalized)
        events = list(controller.outbox._queue)
        self.assertTrue(any(isinstance(event, tuple) and event[0] == "audio" for event in events))
        self.assertEqual(self.svc.memory.latest_fact("customer-test", "preference"), "màu xanh")
        self.assertEqual((await self.store.get(controller.source(record)))["status"], "committed")

    async def test_transcript_can_arrive_after_model_completion(self):
        controller = await self.make_controller()
        await controller.provider_event({"server_content": {
            "output_transcription": {"text": "Vâng."}, "turn_complete": True}})
        await controller.provider_event({"server_content": {
            "input_transcription": {"text": "Tôi thích màu xanh", "finished": True}}})
        await asyncio.gather(*list(controller.jobs))
        self.assertEqual(self.svc.memory.latest_fact("customer-test", "preference"), "màu xanh")

    async def test_interruption_is_not_a_successful_mutation_or_complete_transcript(self):
        controller = await self.make_controller()
        await controller.provider_event({"server_content": {
            "input_transcription": {"text": "cho tôi", "finished": False},
            "model_turn": {"parts": [{"inline_data": {"data": b"\0\0"}}]}}})
        old = controller.current
        await controller.provider_event({"server_content": {"interrupted": True}})
        await asyncio.gather(*list(controller.jobs))
        self.assertTrue(old.interrupted)
        self.assertGreater(controller.generation, old.generation)
        self.assertEqual((await self.store.get(controller.source(old)))["status"], "incomplete")
        self.assertIsNone(self.svc.memory.latest_fact("customer-test", "preference"))

    async def test_prepared_learning_batch_replays_without_duplicate_appends(self):
        ctx = context(self.svc)
        persister = LLMPersister.__new__(LLMPersister)
        persister.memory = self.svc.memory
        persister.structured_llm = SimpleNamespace(ainvoke=AsyncMock(return_value=EpisodeSummarySchema(
            facts_established="Khách thích màu xanh", foresights=["Hỏi lại màu xanh lần sau"])))
        self.svc.persist = persister
        await self.store.save("voice:test:turn", "customer-test", {"input_text": ctx.input.text})
        original = self.store.committed
        with patch.object(self.store, "committed", side_effect=RuntimeError("crash after canonical write")):
            with self.assertRaises(RuntimeError):
                await commit_voice(self.svc, ctx, self.store, "voice:test:turn")
        before = self.svc.memory.load("customer-test")
        await commit_voice(self.svc, context(self.svc), self.store, "voice:test:turn")
        self.assertEqual(before, self.svc.memory.load("customer-test"))
        self.assertEqual(persister.structured_llm.ainvoke.await_count, 1)
        self.assertEqual((await self.store.get("voice:test:turn"))["status"], "committed")
        await original("voice:test:turn")

    async def test_newer_fact_is_not_overwritten_by_pending_replay(self):
        ctx = context(self.svc)
        await self.store.save("voice:test:turn", "customer-test", {})
        with patch.object(self.store, "committed", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                await commit_voice(self.svc, ctx, self.store, "voice:test:turn")
        self.svc.memory.upsert_fact("customer-test", "preference", "màu đỏ")
        await commit_voice(self.svc, context(self.svc), self.store, "voice:test:turn")
        self.assertEqual(self.svc.memory.latest_fact("customer-test", "preference"), "màu đỏ")

    async def test_write_tool_is_denied_even_if_model_requests_it(self):
        mutation = SimpleNamespace(ainvoke=AsyncMock())
        self.svc.mcp_tools["create_new_order"] = mutation
        ctx = context(self.svc)
        result, evidence = await dispatch(self.svc, RealtimeSettings(), ctx.state, ctx,
                                           "create_new_order", {"customer_id": "other"}, "call-1")
        self.assertEqual(result["error"], "tool_not_allowed")
        self.assertIsNone(evidence)
        mutation.ainvoke.assert_not_awaited()
        self.assertNotIn("create_new_order", [x["name"] for x in tool_declarations(self.svc.mcp_tools, "read_only")])

    async def test_read_tool_binds_identity_and_rejects_injected_customer(self):
        tool = SimpleNamespace(ainvoke=AsyncMock(return_value={"stock": 3}))
        self.svc.mcp_tools["check_inventory"] = tool
        ctx = context(self.svc)
        ctx.perception = Perception(transcript=ctx.input.text, intent="ask_product")
        result, _ = await dispatch(self.svc, RealtimeSettings(), ctx.state, ctx, "check_inventory",
                                   {"sku": "SKU-1", "customer_id": "other"}, "call-2")
        self.assertEqual(result["error"], "invalid_arguments")
        result, evidence = await dispatch(self.svc, RealtimeSettings(), ctx.state, ctx,
                                          "check_inventory", {"sku": "SKU-1"}, "call-3")
        self.assertEqual(result["stock"], 3)
        self.assertEqual(evidence["name"], "inventory.check")

    async def test_session_token_and_ticket_cannot_be_reused_or_crossed(self):
        manager = VoiceSessionManager(self.svc, RealtimeSettings(), self.store,
                                      model_factory=lambda *args: SimpleNamespace())
        item = await manager.create("0900000000")
        with self.assertRaises(PermissionError):
            manager.claim(item["session_id"], "wrong-owner", item["connect_ticket"])
        manager.claim(item["session_id"], item["owner_token"], item["connect_ticket"])
        with self.assertRaises(PermissionError):
            manager.claim(item["session_id"], item["owner_token"], item["connect_ticket"])
        cancelled = await manager.create("0900000000")
        manager.owned(cancelled["session_id"], cancelled["owner_token"]).controller.closed = True
        with self.assertRaises(PermissionError):
            manager.claim(cancelled["session_id"], cancelled["owner_token"], cancelled["connect_ticket"])
        await manager.close()

    async def test_prompt_context_masks_pii_without_changing_memory(self):
        state = ConversationState("test", call_brief=CallBrief(
            customer_id="customer-test", summary="SĐT 0900000000"))
        result = brief_data(state)
        self.assertNotIn("0900000000", str(result))
        self.assertIn("0900000000", state.call_brief.summary)

    async def test_tool_pii_masking_preserves_numeric_price_and_result_structure(self):
        value = {"price": 123456789, "contacts": [{"phone": "0900000000"}]}
        safe = public_data(value)
        self.assertEqual(safe["price"], 123456789)
        self.assertNotIn("0900000000", str(safe))
        self.assertEqual(value["contacts"][0]["phone"], "0900000000")

    async def test_config_does_not_allow_unaudited_writes_or_a_different_model(self):
        with patch.dict("os.environ", {"REALTIME_TOOLS_MODE": "read_write"}):
            with self.assertRaises(ValueError):
                RealtimeSettings.from_env()
        with patch.dict("os.environ", {"GEMINI_LIVE_MODEL": "another-model"}):
            with self.assertRaises(ValueError):
                RealtimeSettings.from_env()

    async def test_sdk_configuration_is_valid_without_text_thinking_options(self):
        from google.genai import types
        captured = {}
        session = SimpleNamespace(send_realtime_input=AsyncMock(), send_tool_response=AsyncMock())
        class Connection:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *args):
                pass
        def connect(**kwargs):
            captured.update(kwargs)
            types.LiveConnectConfig.model_validate(kwargs["config"])
            return Connection()
        fake = SimpleNamespace(aio=SimpleNamespace(
            live=SimpleNamespace(connect=connect), aclose=AsyncMock()))
        with patch("google.genai.Client", return_value=fake), patch.dict("os.environ", {"GOOGLE_API_KEY": "test-only"}):
            model = GeminiLiveClient(RealtimeSettings(), "Tiếng Việt", tool_declarations({}, "read_only"))
            await model.open()
            await model.audio(b"\0\0" * 320)
            await model.tool_result("call-1", "get_customer_context", {"context": {}})
            await model.close()
        self.assertEqual(captured["model"], "gemini-3.8-live")
        self.assertNotIn("thinking_config", captured["config"])
        self.assertNotIn("proactivity", captured["config"])
        session.send_realtime_input.assert_awaited_once()
        session.send_tool_response.assert_awaited_once()

    def test_http_bootstrap_and_websocket_route_use_scoped_tickets(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect
        from telesale_agent.entrypoints.api.voice import create_voice_router
        class Model:
            def __init__(self, *args):
                self.queue = asyncio.Queue()
                self.closed = False
            async def open(self):
                pass
            async def close(self):
                self.closed = True
            async def events(self):
                while True:
                    yield await self.queue.get()
            async def audio(self, data):
                await self.queue.put({"server_content": {
                    "input_transcription": {"text": "Tôi thích màu xanh", "finished": True},
                    "model_turn": {"parts": [{"inline_data": {"data": data}}]},
                    "turn_complete": True}})
        manager = VoiceSessionManager(self.svc, RealtimeSettings(), self.store, model_factory=Model)
        router, _ = create_voice_router(lambda: self.svc, manager_factory=lambda *args: manager)
        app = FastAPI()
        app.include_router(router)
        with patch.dict("os.environ", {"REALTIME_VOICE_ENABLED": "true", "API_KEY": "test-access"}):
            with TestClient(app) as client:
                self.assertEqual(client.post("/api/voice/sessions", json={}).status_code, 401)
                created = client.post("/api/voice/sessions", json={"customer_phone": "0900000000"},
                                      headers={"X-API-Key": "test-access"})
                self.assertEqual(created.status_code, 200)
                item = created.json()
                path = "/api/voice/sessions/" + item["session_id"] + "/stream"
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect(path, headers={"Origin": "https://untrusted.invalid"}):
                        pass
                with client.websocket_connect(path, headers={"Origin": "http://localhost:3000"}) as ws:
                    ws.send_json({"type": "authenticate", "owner_token": item["owner_token"],
                                  "connect_ticket": item["connect_ticket"]})
                    self.assertEqual(ws.receive_json()["type"], "session_ready")
                    ws.send_bytes(b"\0\0" * 320)
                    self.assertEqual(ws.receive_json()["type"], "transcript_update")
                    self.assertEqual(ws.receive_json()["type"], "audio")
                    self.assertEqual(ws.receive_bytes(), b"\0\0" * 320)
                    ws.send_json({"type": "close"})
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect(path, headers={"Origin": "http://localhost:3000"}) as ws:
                        ws.send_json({"type": "authenticate", "owner_token": item["owner_token"],
                                      "connect_ticket": item["connect_ticket"]})
                        ws.receive_json()
                self.assertEqual(client.get("/api/voice/sessions/" + item["session_id"],
                                             headers={"Authorization": "Bearer wrong"}).status_code, 404)
if __name__ == "__main__":
    unittest.main()
