import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from telesale_agent.application.memory.call_brief import CallBriefProjector
from telesale_agent.adapters.llm.llm_perceive import canonicalize_memory_deltas
from telesale_agent.core.models import CallBrief, Channel, ConversationState, CustomerIdentity, Perception, TurnContext, TurnInput
from telesale_agent.entrypoints.api import chat


class CallBriefPreviewTests(unittest.TestCase):
    def setUp(self):
        self.brief = CallBrief(
            customer_id="internal-customer-id",
            customer_name="Internal name",
            summary="Tư vấn máy lọc không khí.",
            needs=["Phòng ngủ yên tĩnh"],
            objections=["Chi phí thay màng"],
            unresolved_issues=["Xác nhận diện tích"],
            verified_customer_data={"address": "internal-address"},
            remembered_preferences={"facts": {"private": True}},
            relevant_episodes=[{"summary": "internal-history"}],
        )
        self.result = SimpleNamespace(
            response_text="Mình sẽ tư vấn.", latency={}, perception=None, retrieved=None,
            state=ConversationState("test"), tool_calls=[], memory_writes=[], usage={},
            call_brief=self.brief,
        )

    def test_compact_brief_is_always_returned_without_enabling_debug(self):
        for enabled in ("false", "true"):
            with self.subTest(debug=enabled), patch.dict(os.environ, {"ENABLE_DEBUG_RESPONSE": enabled}), patch.object(chat.provider_cooldown, "remaining", return_value=0):
                response = chat.turn_payload(TurnInput("test", text="xin chào"), self.result)
            self.assertEqual(response["call_brief"]["summary"], self.brief.summary)
            self.assertEqual(set(response["call_brief"]), {"summary", "needs", "objections", "unresolved_issues"})
            if enabled == "false":
                self.assertNotIn("debug", response)
                self.assertNotIn("crm_profile", response)
                self.assertNotIn("customer_memory", response)

    def test_text_and_audio_debug_include_only_compact_brief_fields(self):
        expected = {"summary": self.brief.summary, "needs": self.brief.needs,
                    "objections": self.brief.objections, "unresolved_issues": self.brief.unresolved_issues}
        with patch.dict(os.environ, {"ENABLE_DEBUG_RESPONSE": "true"}), patch.object(chat.provider_cooldown, "remaining", return_value=0):
            for channel in (Channel.CHAT, Channel.VOICE):
                with self.subTest(channel=channel):
                    response = chat.turn_payload(TurnInput("test", text="xin chào", channel=channel), self.result)
                    self.assertEqual(response["debug"]["call_brief"], expected)
                    self.assertEqual(response["call_brief"], expected)
                    self.assertNotIn("customer_id", response["debug"]["call_brief"])
                    self.assertNotIn("verified_customer_data", response["debug"]["call_brief"])

    def test_preview_bounds_large_briefs_and_supports_missing_brief(self):
        self.assertIsNone(chat._call_brief_preview(None))
        self.brief.summary = "x" * 5000
        self.brief.needs = ["n" * 1500] * 20
        result = chat._call_brief_preview(self.brief)
        self.assertEqual(len(result["summary"]), 4000)
        self.assertEqual(len(result["needs"]), 12)
        self.assertTrue(all(len(item) == 1000 for item in result["needs"]))

    def test_public_brief_masks_pii_without_modifying_pipeline_context(self):
        self.brief.summary = "Liên hệ 0901234567, CCCD 123456789012, STK: 12345678901"
        self.brief.needs = ["Số điện thoại 0901234567"]
        result = chat._call_brief_preview(self.brief)
        for secret in ("0901234567", "123456789012", "12345678901"):
            self.assertNotIn(secret, str(result))
        self.assertIn("0901234567", self.brief.summary)

    def test_numeric_budget_facts_are_not_mistaken_for_identity_numbers(self):
        self.brief.summary = "Customer facts: budget_vnd: 100000000, phone: 0901234567"
        self.brief.needs = ["budget_vnd: 100000000", "price_quoted_vnd: 123456789"]
        result = chat._call_brief_preview(self.brief)
        self.assertIn("100000000", result["summary"])
        self.assertNotIn("0901234567", result["summary"])
        self.assertEqual(result["needs"], self.brief.needs)

    def test_text_and_audio_routes_return_current_brief_with_debug_disabled(self):
        async def run(item, state):
            if item.audio:
                item.text = "Ngân sách 4 triệu"
            amount = 4_000_000 if "4 triệu" in item.text else 3_000_000
            context = TurnContext(input=item, state=state,
                identity=CustomerIdentity(customer_id="test"),
                perception=Perception(transcript=item.text, intent="product", memory_deltas={"budget_vnd": amount}))
            state.customer_memory = {"facts": {"budget_vnd": amount}}
            brief = await CallBriefProjector().build_call_brief(context)
            return SimpleNamespace(**{**vars(self.result), "state": state, "call_brief": brief})

        with patch.object(chat, "harness", SimpleNamespace(run_turn=AsyncMock(side_effect=run))), patch.dict(os.environ, {"API_KEY": "", "ENABLE_DEBUG_RESPONSE": "false"}), patch.object(chat.provider_cooldown, "remaining", return_value=0):
            chat.sessions.clear()
            chat.session_locks.clear()
            client = TestClient(chat.app)
            try:
                text = client.post("/api/chat", json={"conversation_id": "brief-live", "message": "Ngân sách 3 triệu"})
                self.assertEqual(text.status_code, 200)
                self.assertIn("3000000", text.json()["call_brief"]["summary"])
                audio = client.post("/api/chat/audio", data={"conversation_id": "brief-live"}, files={"file": ("demo.wav", b"speech", "audio/wav")})
                self.assertEqual(audio.status_code, 200)
                self.assertEqual(audio.json()["transcript"], "Ngân sách 4 triệu")
                self.assertIn("4000000", audio.json()["call_brief"]["summary"])
                self.assertNotIn("3000000", audio.json()["call_brief"]["summary"])
                for response in (text, audio):
                    self.assertNotIn("debug", response.json())
                    self.assertNotIn("customer_id", response.json()["call_brief"])
                self.assertEqual(chat.harness.run_turn.await_count, 2)
            finally:
                client.close()
                chat.sessions.clear()
                chat.session_locks.clear()


class CallBriefFreshnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_budget_corrections_are_accepted_without_adopting_cart_totals(self):
        for text in (
            "Mình đổi ngân sách tối đa lên 4 triệu.",
            "Mình đổi ngân sách tối đa thành 4 triệu.",
            "Ngân sách của mình giảm xuống còn 4 triệu.",
        ):
            with self.subTest(text=text):
                self.assertEqual(canonicalize_memory_deltas({"budget_vnd": 4_000_000}, text)["budget_vnd"], 4_000_000)
        for text in ("Tổng giỏ hàng 4 triệu vẫn nằm trong ngân sách.", "Báo giá 4 triệu này là giá của máy nào?"):
            with self.subTest(text=text):
                self.assertNotIn("budget_vnd", canonicalize_memory_deltas({"budget_vnd": 4_000_000}, text))

    async def test_current_facts_take_precedence_without_mutating_memory(self):
        state = ConversationState("fresh", customer_memory={"facts": {
            "budget_vnd": 3_000_000, "room_area_m2": 25,
            **{f"old_{index}": index for index in range(15)},
        }}, memory_deltas={"budget_vnd": 4_000_000, "blocker": "Chi phí màng lọc"})
        context = TurnContext(input=TurnInput("fresh", text="Tăng ngân sách lên 4 triệu"), state=state,
            identity=CustomerIdentity(customer_id="test"),
            perception=Perception(transcript="Tăng ngân sách lên 4 triệu", memory_deltas={"budget_vnd": 4_000_000}))
        brief = await CallBriefProjector().build_call_brief(context)
        self.assertEqual(brief.needs[0], "budget_vnd: 4000000")
        self.assertIn("4000000", brief.summary)
        self.assertEqual(brief.objections, ["Chi phí màng lọc"])
        self.assertEqual(state.customer_memory["facts"]["budget_vnd"], 3_000_000)
        self.assertEqual(state.memory_deltas["budget_vnd"], 4_000_000)

    async def test_committed_facts_are_not_overwritten_by_rejected_perception_values(self):
        state = ConversationState("committed", customer_memory={"facts": {"budget_vnd": 4_000_000, "blocker": "Cần hỏi rõ bảo hành"}})
        context = TurnContext(input=TurnInput("committed", text="Để tôi cân nhắc"), state=state,
            identity=CustomerIdentity(customer_id="test"),
            perception=Perception(transcript="Để tôi cân nhắc", memory_deltas={"blocker": "Đang cân nhắc"}))
        brief = await CallBriefProjector().build_call_brief(context)
        self.assertEqual(brief.objections, ["Cần hỏi rõ bảo hành"])


if __name__ == "__main__":
    unittest.main()
