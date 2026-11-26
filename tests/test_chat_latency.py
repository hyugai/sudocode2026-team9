"""Complete chat responses, guardrails and official backend timing boundaries."""
import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from telesale_agent.application.deepagent.turn import run_turn_impl, prepare_response
from telesale_agent.adapters.rules.pii_guardrail import PIIGuardrail
from telesale_agent.core.models import TurnInput, TurnContext, CustomerIdentity, CallBrief, ConversationState, Perception, Channel


class CompleteTurnTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, *, audio=False, answer="Xin chào chị.", guardrail=None, arrival=0, persist_seconds=1, persisted_facts=None):
        clock = [0.1]  # Includes 100 ms of backend work/queueing before harness entry.
        async def asr(context):
            clock[0] += .5
            return "xin chào"
        async def identity(context):
            clock[0] += .003
            return CustomerIdentity(customer_id="test", phone="0901234567")
        async def brief(context):
            clock[0] += .004
            return CallBrief(customer_id="test")
        async def invoke(*args, **kwargs):
            clock[0] += .05
            return {"messages": [AIMessage(content=answer)]}
        async def persist(context):
            self.assertEqual(context.state.messages[-1].role, "agent")
            if persisted_facts is not None:
                context.state.customer_memory = {"facts": persisted_facts}
            clock[0] += persist_seconds
            return []
        agent = SimpleNamespace(ainvoke=AsyncMock(side_effect=invoke), astream=AsyncMock(side_effect=AssertionError("Must invoke once")))
        harness = SimpleNamespace(agent=agent, asr=SimpleNamespace(transcribe=asr),
            identity=SimpleNamespace(resolve_identity=identity), customer_context=None, perceive=None,
            retrieve=None, call_brief=SimpleNamespace(build_call_brief=brief), guardrail=guardrail,
            persist=SimpleNamespace(persist=persist), _prefetch_read_tools=AsyncMock(return_value=([], frozenset())),
            _execute_confirmed_mutation=AsyncMock(return_value=([], frozenset())))
        timer = SimpleNamespace(perf_counter=lambda: clock[0])
        item = TurnInput("test", audio=b"speech" if audio else None, text=None if audio else "xin chào",
                         customer_hint="0901234567", metadata={"_latency_started_at": arrival})
        with patch("telesale_agent.application.deepagent.turn.time", timer), patch(
                "telesale_agent.application.conversation.prepare.time", timer):
            result = await run_turn_impl(harness, item)
        agent.ainvoke.assert_awaited_once()
        agent.astream.assert_not_called()
        return result

    async def test_text_latency_ends_before_persistence_and_includes_backend_queueing(self):
        result = await self.exercise()
        self.assertEqual(result.response_text, "Xin chào chị.")
        self.assertEqual(result.state.turn_number, 1)
        self.assertEqual(result.latency["measurement_mode"], "non_streaming")
        self.assertEqual(result.latency["timing_boundary"], "response_ready_before_persistence")
        self.assertEqual(result.latency["ttft_ms"], 157)
        self.assertEqual(result.latency["total_ms"], 157)
        self.assertEqual(result.latency["response_ready_ms"], 157)
        self.assertEqual(result.latency["persistence_ms"], 1000)
        self.assertEqual(result.latency["request_complete_ms"], 1157)
        self.assertEqual(result.latency["backend_total_ms"], 1157)
        self.assertEqual(result.latency["call_brief_ms"], 107)
        self.assertIsNone(result.latency["ttfa_ms"])

    async def test_offline_asr_is_separate_from_ttft_and_total(self):
        result = await self.exercise(audio=True)
        self.assertEqual(result.latency["asr_ms"], 500)
        self.assertEqual(result.latency["ttft_ms"], 157)
        self.assertEqual(result.latency["total_ms"], 157)
        self.assertEqual(result.latency["request_complete_ms"], 1157)
        self.assertEqual(result.latency["backend_total_ms"], 1657)
        # The guide only excludes ASR from M1 TTFT/Total, not Call Brief.
        self.assertEqual(result.latency["call_brief_ms"], 607)

    async def test_slower_persistence_does_not_increase_answer_latency(self):
        fast = await self.exercise(persist_seconds=1)
        slow = await self.exercise(persist_seconds=4)
        self.assertEqual(fast.latency["ttft_ms"], slow.latency["ttft_ms"])
        self.assertEqual(fast.latency["total_ms"], slow.latency["total_ms"])
        self.assertEqual(slow.latency["persistence_ms"], 4000)
        self.assertEqual(slow.latency["request_complete_ms"], fast.latency["request_complete_ms"] + 3000)

    async def test_completed_turn_returns_brief_after_current_facts_are_committed(self):
        result = await self.exercise(persisted_facts={"budget_vnd": 4_000_000, "room_area_m2": 25})
        self.assertIn("budget_vnd: 4000000", result.call_brief.needs)
        self.assertIn("4000000", result.call_brief.summary)
        self.assertIs(result.state.call_brief, result.call_brief)

    async def test_anonymous_brief_retains_facts_across_text_and_audio_without_durable_writes(self):
        from telesale_agent.application.customer_context import CustomerContextService
        from telesale_agent.application.memory.call_brief import CallBriefProjector
        from telesale_agent.adapters.memory.in_memory import InMemoryCustomerMemoryRepository
        from telesale_agent.adapters.memory.turn_persist import TurnMemoryPersister

        memory = InMemoryCustomerMemoryRepository()
        crm = SimpleNamespace(retrieve_profile=AsyncMock(), precompute_brief=AsyncMock())
        facts = iter([
            {"budget_vnd": 3_000_000, "room_area_m2": 25},
            {"budget_vnd": 4_000_000},
            {"budget_vnd": 5_000_000},
            {},
        ])

        async def perceive(context):
            return Perception(transcript=context.input.text, intent="provide_info", memory_deltas=next(facts))

        harness = SimpleNamespace(
            agent=SimpleNamespace(ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="Đã ghi nhận.")]})),
            asr=SimpleNamespace(transcribe=AsyncMock(return_value="Ngân sách 5 triệu")),
            identity=SimpleNamespace(resolve_identity=AsyncMock(return_value=CustomerIdentity())),
            customer_context=CustomerContextService(crm, memory),
            perceive=SimpleNamespace(perceive=perceive), retrieve=None,
            call_brief=CallBriefProjector(), guardrail=None, persist=TurnMemoryPersister(memory),
            _prefetch_read_tools=AsyncMock(return_value=([], frozenset())),
            _execute_confirmed_mutation=AsyncMock(return_value=([], frozenset())),
        )
        state = ConversationState("anonymous")
        for amount, item in (
            (3_000_000, TurnInput("anonymous", text="Ngân sách 3 triệu, phòng 25 m2")),
            (4_000_000, TurnInput("anonymous", text="Ngân sách lên 4 triệu")),
            (5_000_000, TurnInput("anonymous", audio=b"speech", channel=Channel.VOICE)),
        ):
            result = await run_turn_impl(harness, item, state)
            self.assertIn(f"budget_vnd: {amount}", result.call_brief.needs)
            self.assertIn("room_area_m2: 25", result.call_brief.needs)
            self.assertEqual(result.memory_writes, [])
            self.assertEqual(state.memory_deltas, {})
            self.assertIsNone(state.customer_memory)

        # A fresh conversation cannot inherit another anonymous guest's brief.
        other = await run_turn_impl(harness, TurnInput("other", text="Xin chào"))
        self.assertNotIn("budget_vnd", str(other.call_brief.needs))
        crm.retrieve_profile.assert_not_awaited()
        crm.precompute_brief.assert_not_awaited()

    async def test_full_answer_is_guarded_before_it_is_returned(self):
        result = await self.exercise(answer="Số điện thoại 0901234567. Em đã ghi nhận.", guardrail=PIIGuardrail())
        self.assertNotIn("0901234567", result.response_text)

    async def test_basket_grounding_keeps_one_confirmation_per_real_order(self):
        context = TurnContext(input=TurnInput("basket", text="Chị chốt giỏ hàng."), state=ConversationState("basket"))
        context.call_brief = CallBrief(customer_id="test", remembered_preferences={"facts": {
            "basket_skus": ["A", "B"], "basket_product_names": {"A": "Máy A", "B": "Máy B"}}})
        calls = [{"name": "order.create", "args": {"sku": sku}, "result": {"order_id": "ORD-" + sku}} for sku in ("A", "B")]
        answer = await prepare_response(SimpleNamespace(guardrail=None), context, calls, "Đã lên đơn.", basket_evidence=calls + calls)
        self.assertEqual(answer.count("Máy A — mã đơn ORD-A"), 1)
        self.assertEqual(answer.count("Máy B — mã đơn ORD-B"), 1)


class CompleteChatAPITests(unittest.TestCase):
    def test_text_and_audio_always_return_json_including_legacy_stream_flag(self):
        from telesale_agent.entrypoints.api import chat
        async def run(item, state):
            self.assertIn("_latency_started_at", item.metadata)
            if item.audio:
                self.assertEqual(item.audio, b"speech")
                self.assertTrue(item.metadata["offline_audio"])
                item.text = "xin chào"
            state.turn_number += 1
            return SimpleNamespace(response_text="Xin chào chị.", state=state,
                latency={"measurement_mode": "non_streaming", "ttft_ms": 25, "total_ms": 25, "ttfa_ms": None, "call_brief_ms": 4})
        with patch.object(chat, "harness", SimpleNamespace(run_turn=AsyncMock(side_effect=run))), patch.dict(
                os.environ, {"API_KEY": "", "ENABLE_DEBUG_RESPONSE": "false"}), patch.object(chat.provider_cooldown, "remaining", return_value=0):
            chat.sessions.clear()
            chat.session_locks.clear()
            client = TestClient(chat.app)
            try:
                for legacy in (False, True):
                    text = client.post("/api/chat", json={"conversation_id": "json", "message": "xin chào", "stream": legacy})
                    audio = client.post("/api/chat/audio", data={"conversation_id": "json", "stream": str(legacy).lower()},
                        files={"file": ("voice.wav", b"speech", "audio/wav")})
                    for response in (text, audio):
                        self.assertEqual(response.status_code, 200)
                        self.assertIn("application/json", response.headers["content-type"])
                        self.assertEqual(int(response.headers["content-length"]), len(response.content))
                        payload = response.json()
                        self.assertEqual(payload["response"], "Xin chào chị.")
                        self.assertEqual(payload["call_brief_latency_ms"], 4)
                        self.assertEqual(payload["latency"]["total_ms"], 25)
                        self.assertEqual(payload["latency"]["ttft_ms"], payload["latency"]["total_ms"])
                    self.assertEqual(audio.json()["transcript"], "xin chào")
                self.assertEqual(chat.sessions["json"].turn_number, 4)
            finally:
                client.close()
                chat.sessions.clear()
                chat.session_locks.clear()


class ArrivalBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_emission_preserves_answer_latency_and_times_request_separately(self):
        from telesale_agent.entrypoints.api.chat import ArrivalTimingMiddleware
        clock = [0.0]
        emitted = []
        async def application(scope, receive, send):
            clock[0] = .8
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", b"1")]})
            clock[0] = 1
            body = json.dumps({"response": "Xin chào", "latency": {
                "measurement_mode": "non_streaming", "asr_ms": 500,
                "ttft_ms": 250, "total_ms": 250, "response_ready_ms": 250, "persistence_ms": 200}}).encode()
            await send({"type": "http.response.body", "body": body})
        async def send(message):
            emitted.append(message)
            clock[0] += 5  # Time spent sending to a client is outside backend timing.
        with patch("telesale_agent.entrypoints.api.chat.time", SimpleNamespace(perf_counter=lambda: clock[0])):
            await ArrivalTimingMiddleware(application)({"type": "http", "path": "/api/chat/audio"}, None, send)
        latency = json.loads(emitted[-1]["body"])["latency"]
        self.assertEqual(latency["ttft_ms"], 250)
        self.assertEqual(latency["total_ms"], 250)
        self.assertEqual(latency["response_ready_ms"], 250)
        self.assertEqual(latency["persistence_ms"], 200)
        self.assertEqual(latency["request_complete_ms"], 500)
        self.assertEqual(latency["backend_total_ms"], 1000)


class CallBriefFreshnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_freshness_reads_finish_inside_call_brief_latency(self):
        from datetime import date
        from telesale_agent.application.conversation.prepare import prepare_context
        from telesale_agent.application.memory.call_brief import FreshCallBrief
        from unittest.mock import Mock
        clock = [0.0]
        async def identity(context):
            clock[0] += .003
            return CustomerIdentity(customer_id="test", phone="0901234567")
        async def build(context):
            clock[0] += .004
            return CallBrief(customer_id="test")
        def read(value):
            def execute(*args, **kwargs):
                clock[0] += .01
                return value
            return execute
        db = SimpleNamespace(check_stock=Mock(side_effect=read({"in_stock": True})),
            search_products=Mock(side_effect=read({"items": [{"category": "air"}]})),
            get_active_promotions=Mock(side_effect=read([{"promo_id": "active"}])))
        state = ConversationState("freshness")
        state.customer_memory = {"facts": {"product_advised": "SKU-X"}}
        context = TurnContext(input=TurnInput("freshness", text="xin chào", metadata={"call_date": "2026-10-31"}), state=state)
        harness = SimpleNamespace(identity=SimpleNamespace(resolve_identity=identity), customer_context=None,
            perceive=None, retrieve=None, call_brief=FreshCallBrief(SimpleNamespace(build_call_brief=build), db))
        with patch("telesale_agent.application.conversation.prepare.time", SimpleNamespace(perf_counter=lambda: clock[0])):
            latency = await prepare_context(harness, context, identity_started=0)
        self.assertAlmostEqual(latency, 37)
        db.check_stock.assert_called_once_with("SKU-X", date(2026, 10, 31))
        self.assertEqual(context.call_brief.active_promotions, [{"promo_id": "active"}])
        self.assertIn("freshness_check", context.call_brief.verified_customer_data)


if __name__ == "__main__":
    unittest.main()
