"""Answer emission, privacy, disconnects and backend latency boundaries."""
import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from langchain_core.messages import AIMessage, AIMessageChunk
from fastapi.testclient import TestClient
from telesale_agent.application.deepagent.streaming import stream_events, chunk_text
from telesale_agent.application.deepagent.turn import run_turn_impl, prepare_response
from telesale_agent.adapters.rules.pii_guardrail import PIIGuardrail
from telesale_agent.core.models import TurnInput, TurnContext, CustomerIdentity, CallBrief, ConversationState


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, *, tool_turn=False, mutation_turn=False, parts=None, guardrail=None, agent_override=None):
        clock = [0.0]
        events = []
        parts = parts or ["Xin chào chị. ", "Em hỗ trợ mình nhé."]
        async def asr(context):
            clock[0] += .5
            return "xin chào"
        async def identity(context):
            clock[0] += .003
            return CustomerIdentity(customer_id="test")
        async def brief(context):
            clock[0] += .004
            return CallBrief(customer_id="test")
        async def native_stream(*args, **kwargs):
            self.assertEqual(kwargs["stream_mode"], ["messages", "values", "custom"])
            yield "messages", (AIMessageChunk(content=[{"type":"reasoning", "text":"PRIVATE THOUGHT"}]), {"langgraph_node":"model"})
            for text in parts:
                clock[0] += .02
                yield "messages", (AIMessageChunk(content=text), {"langgraph_node":"model"})
            clock[0] += .01
            yield "values", {"messages":[AIMessage(content="".join(parts))]}
        async def reads(*args):
            return [], (frozenset({"create_new_order"}) if mutation_turn
                        else frozenset({"search_policy"}) if tool_turn else frozenset())
        async def mutations(context, allowed, verified):
            return [], allowed
        async def persist(context):
            self.assertTrue(any(e["type"] == "response_complete" for e in events))
            clock[0] += 1
            return []
        harness = SimpleNamespace(agent=agent_override or SimpleNamespace(astream=native_stream),
            asr=SimpleNamespace(transcribe=asr), identity=SimpleNamespace(resolve_identity=identity),
            customer_context=None, perceive=None, retrieve=None, call_brief=SimpleNamespace(build_call_brief=brief),
            persist=SimpleNamespace(persist=persist), guardrail=guardrail,
            _prefetch_read_tools=reads, _execute_confirmed_mutation=mutations)
        timer = SimpleNamespace(perf_counter=lambda: clock[0])
        with patch("telesale_agent.application.deepagent.streaming.time", timer), patch(
                "telesale_agent.application.deepagent.turn.time", timer):
            async def execute(output):
                return await run_turn_impl(harness, TurnInput(conversation_id="test", audio=b"fake"), response_stream=output)
            async for event in stream_events(execute):
                events.append(event)
        return events, events[-1]["result"]

    async def test_first_answer_precedes_generation_end_and_persistence(self):
        events, result = await self.exercise()
        content = [e for e in events if e["type"] in {"delta", "replace"}]
        self.assertGreaterEqual(len(content), 2)
        self.assertGreater(result.latency["chunks_before_generation_complete"], 0)
        self.assertEqual(result.latency["ttft_ms"], 27)
        self.assertEqual(result.latency["total_ms"], 57)
        self.assertEqual(result.latency["persistence_ms"], 1000)
        self.assertEqual(result.latency["request_complete_ms"], 1057)
        self.assertEqual(result.latency["asr_ms"], 500)
        self.assertNotIn("PRIVATE", "".join(e["text"] for e in content))

    async def test_pending_mutation_keeps_confirmation_buffered(self):
        _, result = await self.exercise(mutation_turn=True)
        self.assertEqual(result.latency["stream_policy"], "buffered_tool_turn")
        self.assertEqual(result.latency["ttft_ms"], result.latency["total_ms"])
        self.assertEqual(result.latency["ttft_ms"], 57)

    async def test_words_arrive_before_a_complete_sentence(self):
        events, result = await self.exercise(parts=["Dạ em ", "có thể ", "hỗ trợ chị"])
        first = next(e for e in events if e["type"] == "delta")
        self.assertEqual(first["text"], "Dạ em ")
        self.assertLess(result.latency["ttft_ms"], result.latency["total_ms"])

    async def test_unused_read_tool_does_not_buffer_a_normal_answer(self):
        _, result = await self.exercise(tool_turn=True)
        self.assertGreater(result.latency["chunks_before_generation_complete"], 0)
        self.assertLess(result.latency["ttft_ms"], result.latency["total_ms"])

    async def test_final_model_call_streams_after_real_graph_tool_execution(self):
        from langchain.agents import create_agent
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import ToolMessage
        from langchain_core.outputs import ChatGenerationChunk
        from langchain_core.tools import tool
        from telesale_agent.application.deepagent.tools.routing import IntentToolRoutingMiddleware, TelesaleAgentRuntimeContext

        class ToolThenAnswerModel(BaseChatModel):
            @property
            def _llm_type(self):
                return "local-streaming-test"
            def _generate(self, *args, **kwargs):
                raise AssertionError("This test must consume the model stream")
            def bind_tools(self, tools, **kwargs):
                return self
            async def _astream(self, messages, **kwargs):
                if isinstance(messages[-1], ToolMessage):
                    for text in ("Chính sách ", "đổi trả đã được kiểm tra. ", "Em gửi mình nhé."):
                        yield ChatGenerationChunk(message=AIMessageChunk(content=text))
                else:
                    yield ChatGenerationChunk(message=AIMessageChunk(content=[{"type":"reasoning", "text":"PRIVATE PLAN"}]))
                    yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[
                        {"name":"search_policy", "args":'{"query":"đổi trả"}', "id":"lookup", "index":0}]))
        @tool
        async def search_policy(query: str) -> str:
            """Read a local policy fixture."""
            return "Đổi trả trong 7 ngày."
        with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2":"false", "LANGSMITH_TRACING":"false"}):
            graph = create_agent(ToolThenAnswerModel(), tools=[search_policy],
                                 middleware=[IntentToolRoutingMiddleware()], context_schema=TelesaleAgentRuntimeContext)
            events, result = await self.exercise(tool_turn=True, agent_override=graph)
        emitted = "".join(e.get("text", "") for e in events if e["type"] in {"delta", "replace"})
        self.assertNotIn("PRIVATE PLAN", emitted)
        self.assertIn("Chính sách", emitted)
        self.assertGreater(result.latency["chunks_before_generation_complete"], 0)
        self.assertEqual(result.latency["stream_policy"], "guarded_words")
        self.assertEqual(result.tool_calls[0]["name"], "policy.search")

    async def test_pii_split_across_chunks_is_masked_before_emission(self):
        events, result = await self.exercise(parts=["Số điện thoại 09012", "34567. ", "Em đã ghi nhận."], guardrail=PIIGuardrail())
        emitted = "".join(e.get("text", "") for e in events if e["type"] in {"delta", "replace"})
        self.assertNotIn("0901234567", emitted)
        self.assertNotIn("0901234567", result.response_text)

    async def test_forbidden_claim_is_never_sent_raw(self):
        events, _ = await self.exercise(parts=["Giá nhập là bí mật. ", "Em hỗ trợ nhé."], guardrail=PIIGuardrail())
        self.assertFalse(any("Giá nhập" in e.get("text", "") for e in events))

    async def test_disconnect_allows_persistence_to_finish_without_replay(self):
        finished = asyncio.Event()
        async def execute(output):
            await output.answer("Đã nhận yêu cầu.")
            await asyncio.sleep(0)
            finished.set()
            return "done"
        iterator = stream_events(execute)
        self.assertEqual((await anext(iterator))["type"], "delta")
        await iterator.aclose()
        await asyncio.wait_for(finished.wait(), 1)

    def test_tool_arguments_are_not_answer_text(self):
        message = AIMessageChunk(content="Private plan", tool_call_chunks=[{"name":"lookup", "args":"{}", "id":"tool", "index":0}])
        self.assertEqual(chunk_text(message), "")

    async def test_basket_grounding_keeps_one_confirmation_per_real_order(self):
        context = TurnContext(input=TurnInput(conversation_id="basket", text="Chị chốt giỏ hàng."),
                              state=ConversationState("basket"))
        context.call_brief = CallBrief(customer_id="test", remembered_preferences={"facts":{
            "basket_skus":["A", "B"], "basket_product_names":{"A":"Máy A", "B":"Máy B"}}})
        calls = [{"name":"order.create", "args":{"sku":sku}, "result":{"order_id":"ORD-"+sku}}
                 for sku in ("A", "B")]
        answer = await prepare_response(SimpleNamespace(guardrail=None), context, calls, "Đã lên đơn.", basket_evidence=calls+calls)
        self.assertIn("Máy A — mã đơn ORD-A", answer)
        self.assertIn("Máy B — mã đơn ORD-B", answer)


class StreamingAPITests(unittest.TestCase):
    def test_sse_response_emits_content_and_final_metadata(self):
        from telesale_agent.entrypoints.api import chat
        async def run(turn_input, state, *, response_stream):
            await response_stream.send({"type":"input", "transcript":turn_input.text})
            await response_stream.answer("Xin chào. ")
            await response_stream.answer("Xin chào. Em hỗ trợ nhé.")
            state.turn_number += 1
            return SimpleNamespace(response_text=response_stream.text, state=state, latency=response_stream.latency())
        with patch.object(chat, "harness", SimpleNamespace(run_turn=run)), patch.dict(os.environ, {"API_KEY":"", "ENABLE_DEBUG_RESPONSE":"false"}):
            chat.sessions.clear()
            chat.session_locks.clear()
            with patch.object(chat.provider_cooldown, "remaining", return_value=0):
                client = TestClient(chat.app)
                try:
                    response = client.post("/api/chat", json={"conversation_id":"stream-test", "message":"xin chào", "stream":True})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("text/event-stream", response.headers["content-type"])
                    events = [json.loads(frame[6:]) for frame in response.text.strip().split("\n\n")]
                    self.assertEqual([e["type"] for e in events], ["input", "delta", "delta", "complete"])
                    self.assertEqual(events[-1]["latency"]["answer_chunks"], 2)
                    self.assertEqual(chat.sessions["stream-test"].turn_number, 1)
                finally:
                    client.close()
                    chat.sessions.clear()
                    chat.session_locks.clear()

    def test_uploaded_audio_can_use_the_same_sse_protocol(self):
        from telesale_agent.entrypoints.api import chat
        async def run(turn_input, state, *, response_stream):
            self.assertEqual(turn_input.audio, b"speech")
            self.assertTrue(turn_input.metadata["offline_audio"])
            turn_input.text = "xin chào"
            await response_stream.send({"type":"input", "transcript":turn_input.text})
            await response_stream.answer("Xin chào chị.")
            return SimpleNamespace(response_text=response_stream.text, state=state, latency=response_stream.latency())
        with patch.object(chat, "harness", SimpleNamespace(run_turn=run)), patch.dict(os.environ, {"API_KEY":"", "ENABLE_DEBUG_RESPONSE":"false"}), patch.object(chat.provider_cooldown, "remaining", return_value=0):
            client = TestClient(chat.app)
            try:
                response = client.post("/api/chat/audio", data={"conversation_id":"audio-stream", "stream":"true"}, files={"file":("voice.wav", b"speech", "audio/wav")})
                self.assertEqual(response.status_code, 200)
                events = [json.loads(frame[6:]) for frame in response.text.strip().split("\n\n")]
                self.assertEqual(events[-1]["transcript"], "xin chào")
                self.assertEqual(events[-1]["latency"]["answer_chunks"], 1)
            finally:
                client.close()
                chat.sessions.clear()
                chat.session_locks.clear()


if __name__ == "__main__":
    unittest.main()
