"""Voice input contract tests; no LLM, CRM, or MCP services are contacted.

Run: python -m unittest discover -s tests -v
The decoder tests use the FFmpeg binary installed by the voice extra.
"""

import asyncio
import io
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from fastapi.testclient import TestClient

from telesale_agent.adapters.asr.config import ASRConfig, MODEL_FILES
from telesale_agent.adapters.asr.zipformer import ZipformerASREngine
from telesale_agent.core.errors import ASRUnavailableError, AudioInputError, AudioTooLargeError
from telesale_agent.core.models import Channel, ConversationState, Message, TurnContext, TurnInput
from telesale_agent.entrypoints.api import chat


def wave_bytes(seconds=0.25, sample_rate=44100, channels=2):
    samples = (np.sin(np.arange(int(seconds * sample_rate)) * 440 * 2 * np.pi / sample_rate) * 8000).astype("<i2")
    samples = np.repeat(samples[:, None], channels, axis=1)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())
    return buffer.getvalue()


def context_for(audio=None, text=None):
    return TurnContext(
        input=TurnInput(conversation_id="test", audio=audio, text=text),
        state=ConversationState(conversation_id="test"),
    )


class ZipformerTests(unittest.IsolatedAsyncioTestCase):
    def test_supported_compressed_formats_decode(self):
        import imageio_ffmpeg

        engine = ZipformerASREngine()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            source.write_bytes(wave_bytes())
            for suffix in ("mp3", "m4a", "flac", "ogg", "webm"):
                with self.subTest(format=suffix):
                    target = Path(directory) / f"recording.{suffix}"
                    subprocess.run(
                        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-i", str(source), str(target)],
                        check=True, capture_output=True, timeout=15,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    samples = engine._decode_audio(target.read_bytes())
                    self.assertEqual(samples.ndim, 1)
                    self.assertGreater(samples.size, 0)
                    self.assertAlmostEqual(samples.size / 16000, 0.25, delta=0.1)

    async def test_stereo_resampled_and_recognizer_cached_across_requests(self):
        streams = []

        def create_stream():
            stream = SimpleNamespace(
                accept_waveform=Mock(), result=SimpleNamespace(text=" xin chào ")
            )
            streams.append(stream)
            return stream

        recognizer = SimpleNamespace(create_stream=create_stream, decode_stream=Mock())
        factory = Mock(return_value=recognizer)
        with tempfile.TemporaryDirectory() as directory:
            for name in MODEL_FILES:
                (Path(directory) / name).write_bytes(b"model fixture")
            engine = ZipformerASREngine(ASRConfig(model_dir=Path(directory)))
            module = SimpleNamespace(OfflineRecognizer=SimpleNamespace(from_transducer=factory))
            with patch.dict(sys.modules, {"sherpa_onnx": module}):
                results = await asyncio.gather(*[
                    engine.transcribe(context_for(audio=wave_bytes())) for _ in range(2)
                ])
        self.assertEqual(results, ["xin chào", "xin chào"])
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs["provider"], "cpu")
        for stream in streams:
            rate, samples = stream.accept_waveform.call_args.args
            self.assertEqual(rate, 16000)
            self.assertEqual(samples.ndim, 1)
            self.assertAlmostEqual(len(samples) / rate, 0.25, places=2)

    async def test_text_does_not_load_voice_dependencies(self):
        engine = ZipformerASREngine()
        with patch.object(engine, "_transcribe_sync") as transcribe:
            self.assertEqual(await engine.transcribe(context_for(text="xin chào")), "xin chào")
            transcribe.assert_not_called()

    async def test_invalid_empty_and_oversized_recordings(self):
        engine = ZipformerASREngine(ASRConfig(max_upload_bytes=8))
        with self.assertRaises(AudioInputError):
            await engine.transcribe(context_for(audio=b""))
        with self.assertRaises(AudioTooLargeError):
            await engine.transcribe(context_for(audio=b"123456789"))
        with self.assertRaises(AudioInputError):
            await engine.transcribe(context_for(audio=b"not wav"))

    async def test_duration_limit_rejects_instead_of_truncating_turn(self):
        engine = ZipformerASREngine(ASRConfig(max_duration_seconds=1))
        with self.assertRaisesRegex(AudioInputError, "1 giây"):
            await engine.transcribe(context_for(audio=wave_bytes(seconds=2)))

    async def test_missing_model_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = ZipformerASREngine(ASRConfig(model_dir=Path(directory)))
            with self.assertRaisesRegex(ASRUnavailableError, "download_asr_model"):
                await engine.transcribe(context_for(audio=wave_bytes()))

    async def test_empty_transcript_does_not_become_a_turn(self):
        engine = ZipformerASREngine()
        recognizer = SimpleNamespace(
            create_stream=lambda: SimpleNamespace(accept_waveform=Mock(), result=SimpleNamespace(text=" ")),
            decode_stream=Mock(),
        )
        with patch.object(engine, "_load_recognizer", return_value=recognizer):
            with self.assertRaisesRegex(AudioInputError, "giọng nói"):
                await engine.transcribe(context_for(audio=wave_bytes()))


class PipelineASRTests(unittest.IsolatedAsyncioTestCase):
    async def test_typed_text_normalized_before_identity_perception_and_main_agent(self):
        from telesale_agent.application.deepagent.turn import run_turn_impl
        from telesale_agent.core.models import CustomerIdentity, Perception

        raw = "sp nay co ship cod k a"
        expected = "Sản phẩm này có ship cod không anh"
        turn_input = context_for(text=raw).input
        state = ConversationState(conversation_id="test")
        stages = []

        class ReachedMainAgent(Exception):
            pass

        async def resolve(context):
            stages.append("identity")
            self.assertEqual(context.input.text, expected)
            self.assertEqual(context.input.metadata["raw_user_text"], raw)
            return CustomerIdentity()

        async def perceive(context):
            stages.append("perception")
            self.assertEqual(context.input.text, expected)
            return Perception(transcript=context.input.text)

        async def invoke(payload, **kwargs):
            stages.append("main_agent")
            self.assertIn(expected, payload["messages"][0]["content"])
            self.assertNotIn(raw, payload["messages"][0]["content"])
            raise ReachedMainAgent

        harness = SimpleNamespace(
            agent=SimpleNamespace(ainvoke=invoke), asr=None,
            identity=SimpleNamespace(resolve_identity=resolve), customer_context=None,
            perceive=SimpleNamespace(perceive=perceive), retrieve=None, call_brief=None,
            _prefetch_read_tools=AsyncMock(return_value=([], frozenset())),
            _execute_confirmed_mutation=AsyncMock(return_value=([], frozenset())),
        )
        with self.assertRaises(ReachedMainAgent):
            await run_turn_impl(harness, turn_input, state)
        self.assertEqual(stages, ["identity", "perception", "main_agent"])
        self.assertEqual(state.messages[0].content, expected)

    async def test_rate_limit_does_not_accumulate_history_or_failed_checkpoints(self):
        from telesale_agent.application.deepagent.turn import run_turn_impl
        from telesale_agent.core.models import Perception
        import httpx
        from groq import RateLimitError

        error = RateLimitError("Please try again in 7.3575s.", response=httpx.Response(429, request=httpx.Request("POST", "https://example.test")), body={})
        state = ConversationState(conversation_id="test", turn_number=1)
        state.messages = [Message("customer", "trước đó"), Message("agent", "đã trả lời")]
        original = list(state.messages)
        harness = SimpleNamespace(
            agent=SimpleNamespace(ainvoke=AsyncMock(side_effect=error)),
            asr=None, identity=None, customer_context=None, retrieve=None, call_brief=None,
            perceive=SimpleNamespace(perceive=AsyncMock(return_value=Perception(transcript="gửi lại"))),
            checkpointer=SimpleNamespace(adelete_thread=AsyncMock()),
            _prefetch_read_tools=AsyncMock(return_value=([], frozenset())),
            _execute_confirmed_mutation=AsyncMock(return_value=([], frozenset())),
        )
        with patch.dict(os.environ, {"DEEPAGENT_CHECKPOINT_SCOPE": "turn"}):
            for _ in range(3):
                with self.assertRaises(RateLimitError):
                    await run_turn_impl(harness, context_for(text="gửi lại").input, state)
                self.assertEqual(state.messages, original)
                self.assertEqual(state.turn_number, 1)
        self.assertEqual(harness.checkpointer.adelete_thread.await_count, 3)
        harness.checkpointer.adelete_thread.assert_awaited_with("test__turn_2")

    async def test_perception_rate_limit_stops_before_calling_main_agent(self):
        from telesale_agent.adapters.llm.llm_perceive import LLMPerceiver
        import httpx
        from groq import RateLimitError

        error = RateLimitError("Please try again in 2s.", response=httpx.Response(429, request=httpx.Request("POST", "https://example.test")), body={})
        perceiver = LLMPerceiver.__new__(LLMPerceiver)
        perceiver.structured_llm = SimpleNamespace(ainvoke=AsyncMock(side_effect=error))
        with self.assertRaises(RateLimitError):
            await perceiver.perceive(context_for(text="xin chào"))

    async def test_asr_supplies_text_before_perception(self):
        from telesale_agent.application.deepagent.turn import run_turn_impl

        class ReachedPerception(Exception):
            pass

        async def perceive(context):
            self.assertEqual(context.input.text, "xin chào từ ghi âm")
            self.assertEqual(context.input.metadata["raw_asr_transcript"], "XIN CHÀO TỪ GHI ÂM")
            raise ReachedPerception

        harness = SimpleNamespace(
            agent=object(), asr=SimpleNamespace(transcribe=AsyncMock(return_value=" XIN CHÀO TỪ GHI ÂM ")),
            perceive=SimpleNamespace(perceive=perceive), identity=None, customer_context=None,
        )
        state = ConversationState(conversation_id="test")
        with self.assertRaises(ReachedPerception):
            await run_turn_impl(harness, context_for(audio=b"recording").input, state)
        self.assertEqual(state.messages, [])

    async def test_asr_numbers_are_normalized_before_identity_and_perception(self):
        from telesale_agent.application.deepagent.turn import run_turn_impl

        raw = "GIÁ BỐN TRIỆU TÁM TRĂM CHÍN MƯƠI, GỌI SỐ KHÔNG CHÍN TÁM BỐN BẢY HAI SÁU BẢY MỘT BỐN VÀO NGÀY MƯỜI BẢY THÁNG MƯỜI NĂM HAI KHÔNG HAI SÁU"
        expected = "giá 4.890.000, gọi số 0984726714 vào 17/10/2026"

        class ReachedIdentity(Exception):
            pass

        async def resolve(context):
            self.assertEqual(context.input.text, expected)
            self.assertEqual(context.input.metadata["raw_asr_transcript"], raw)
            raise ReachedIdentity

        harness = SimpleNamespace(
            agent=object(), asr=SimpleNamespace(transcribe=AsyncMock(return_value=raw)),
            identity=SimpleNamespace(resolve_identity=resolve),
        )
        with self.assertRaises(ReachedIdentity):
            await run_turn_impl(harness, context_for(audio=b"recording").input)

    async def test_asr_failure_never_reaches_perception_or_history(self):
        from telesale_agent.application.deepagent.turn import run_turn_impl

        for asr in (None, SimpleNamespace(transcribe=AsyncMock(return_value=""))):
            state = ConversationState(conversation_id="test")
            perceive = AsyncMock()
            harness = SimpleNamespace(agent=object(), asr=asr, perceive=perceive)
            with self.assertRaises((ASRUnavailableError, AudioInputError)):
                await run_turn_impl(harness, context_for(audio=b"recording").input, state)
            perceive.assert_not_called()
            self.assertEqual(state.messages, [])


class FakeHarness:
    def __init__(self):
        self.asr = SimpleNamespace(config=ASRConfig(max_upload_bytes=128))
        self.calls = []
        self.error = None

    async def run_turn(self, turn_input, state):
        if self.error:
            raise self.error
        self.calls.append((turn_input, state, len(state.messages)))
        if turn_input.audio is not None and not turn_input.text:
            turn_input.text = "xin chào từ ghi âm"
        state.messages.append(Message("customer", turn_input.text))
        state.messages.append(Message("agent", "Xin chào bạn"))
        state.turn_number += 1
        return SimpleNamespace(response_text="Xin chào bạn", state=state)


class AudioAPITests(unittest.TestCase):
    def setUp(self):
        self.harness = FakeHarness()
        self.harness_patch = patch.object(chat, "harness", self.harness)
        self.env_patch = patch.dict(os.environ, {"API_KEY": "voice-test", "ENABLE_DEBUG_RESPONSE": "false"})
        self.harness_patch.start()
        self.env_patch.start()
        cooldown = chat.provider_cooldown.retry_at
        chat.provider_cooldown.retry_at = 0
        self.addCleanup(setattr, chat.provider_cooldown, "retry_at", cooldown)
        self.addCleanup(self.harness_patch.stop)
        self.addCleanup(self.env_patch.stop)
        chat.sessions.clear()
        chat.session_locks.clear()
        self.client = TestClient(chat.app, headers={"X-API-Key": "voice-test"})
        self.addCleanup(self.client.close)

    def upload(self, content=b"speech", conversation_id="same-call", **kwargs):
        return self.client.post(
            "/api/chat/audio", data={"conversation_id": conversation_id, "customer_phone": "0901234567"},
            files={"file": ("../recording.wav", content, "audio/wav")}, **kwargs,
        )

    def test_text_voice_text_share_state_and_return_transcript(self):
        def text_turn():
            return self.client.post("/api/chat", json={"conversation_id": "same-call", "message": "xin chào"})

        self.assertEqual(text_turn().status_code, 200)
        voice = self.upload()
        self.assertEqual(voice.status_code, 200)
        self.assertEqual(voice.json()["transcript"], "xin chào từ ghi âm")
        self.assertEqual(text_turn().status_code, 200)
        self.assertEqual([call[2] for call in self.harness.calls], [0, 2, 4])
        self.assertEqual(len({id(call[1]) for call in self.harness.calls}), 1)
        voice_input = self.harness.calls[1][0]
        self.assertEqual(voice_input.channel, Channel.VOICE)
        self.assertEqual(voice_input.customer_hint, "0901234567")

    def test_typed_response_returns_normalized_text_and_optional_original_debug(self):
        from telesale_agent.application.deepagent.turn import run_turn_impl
        from telesale_agent.core.models import Perception
        from langchain_core.messages import AIMessage

        async def perceive(context):
            return Perception(transcript=context.input.text)

        pipeline = SimpleNamespace(
            agent=SimpleNamespace(ainvoke=AsyncMock(return_value={
                "messages": [AIMessage(content="Shop có ship cod ạ.")],
            })),
            asr=None, identity=None, customer_context=None, retrieve=None, call_brief=None,
            perceive=SimpleNamespace(perceive=perceive), guardrail=None, persist=None,
            _prefetch_read_tools=AsyncMock(return_value=([], frozenset())),
            _execute_confirmed_mutation=AsyncMock(return_value=([], frozenset())),
        )

        async def run_pipeline(turn_input, state):
            return await run_turn_impl(pipeline, turn_input, state)

        self.harness.run_turn = run_pipeline
        for debug in (False, True):
            with self.subTest(debug=debug), patch.dict(os.environ, {"ENABLE_DEBUG_RESPONSE": str(debug).lower()}):
                response = self.client.post("/api/chat", json={
                    "conversation_id": f"typed-{debug}", "message": "sp nay co ship cod k a",
                })
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["normalized_message"], "Sản phẩm này có ship cod không anh")
                self.assertEqual(body["response"], "Shop có ship cod ạ.")
                self.assertNotIn("transcript", body)
                if debug:
                    self.assertEqual(body["debug"]["raw_user_text"], "sp nay co ship cod k a")
                    self.assertEqual(body["debug"]["normalized_input"], body["normalized_message"])
                else:
                    self.assertNotIn("debug", body)

    def test_invalid_uploads_do_not_call_agent(self):
        self.assertEqual(self.upload(content=b"").status_code, 422)
        self.assertEqual(self.upload(content=b"x" * 129).status_code, 413)
        self.assertEqual(self.upload(conversation_id=" ").status_code, 422)
        self.assertEqual(self.client.post("/api/chat/audio", data={"conversation_id": "test"}).status_code, 422)
        self.assertEqual(self.harness.calls, [])
        self.assertEqual(chat.sessions, {})

    def test_audio_requires_the_same_api_key_as_text(self):
        self.assertEqual(self.upload(headers={"X-API-Key": "wrong"}).status_code, 401)
        self.assertEqual(self.harness.calls, [])

    def test_asr_errors_have_explicit_http_status_and_preserve_history(self):
        self.upload()
        messages = list(chat.sessions["same-call"].messages)
        for error, status in (
            (AudioInputError("invalid audio"), 422),
            (AudioTooLargeError("too large"), 413),
            (ASRUnavailableError("missing local model"), 503),
        ):
            self.harness.error = error
            response = self.upload()
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["detail"], str(error))
            self.assertEqual(chat.sessions["same-call"].messages, messages)

    def test_starting_agent_returns_503(self):
        with patch.object(chat, "harness", None):
            self.assertEqual(self.upload().status_code, 503)

    def test_provider_429_returns_cors_and_cooldown_without_another_agent_call(self):
        import httpx
        from groq import RateLimitError

        self.harness.error = RateLimitError(
            "Please try again in 7.3575s.",
            response=httpx.Response(429, request=httpx.Request("POST", "https://example.test")),
            body={},
        )
        response = self.upload(headers={"Origin": "http://localhost:3000"})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(response.headers["Retry-After"], "8")
        self.assertEqual(response.json()["retry_after_seconds"], 8)
        self.harness.error = None
        self.assertEqual(self.upload().status_code, 429)
        self.assertEqual(self.harness.calls, [])
        self.assertEqual(chat.sessions, {})

    def test_unexpected_provider_error_is_readable_and_has_cors(self):
        self.harness.error = RuntimeError("private upstream failure")
        with self.assertLogs(chat.logger, level="ERROR"):
            response = self.upload(headers={"Origin": "http://localhost:3000"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        self.assertNotIn("private upstream", response.text)

    def test_local_model_upload_smoke_when_weights_are_available(self):
        engine = ZipformerASREngine()
        sample = engine.config.model_dir / "test_wavs/0.wav"
        if not sample.is_file() or not all((engine.config.model_dir / name).is_file() for name in MODEL_FILES):
            self.skipTest("Download local Zipformer weights to enable the real-model smoke test")
        original_run = self.harness.run_turn
        self.harness.asr = engine

        async def run_voice(turn_input, state):
            turn_input.text = await engine.transcribe(TurnContext(input=turn_input, state=state))
            return await original_run(turn_input, state)

        self.harness.run_turn = run_voice
        response = self.upload(content=sample.read_bytes())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("hỗ trợ", response.json()["transcript"].casefold())
        self.assertEqual(chat.sessions["same-call"].messages[0].content, response.json()["transcript"])


class RateLimitTests(unittest.TestCase):
    def test_retry_delay_prefers_header_and_rounds_up_provider_message(self):
        from telesale_agent.adapters.llm.rate_limits import retry_after_seconds

        error = RuntimeError("Please try again in 7.3575s.")
        self.assertEqual(retry_after_seconds(error), 8)
        error.response = SimpleNamespace(headers={"retry-after": "10"})
        self.assertEqual(retry_after_seconds(error), 10)
        self.assertEqual(retry_after_seconds(RuntimeError("no delay")), 30)

    def test_cooldown_expires_and_does_not_shorten_existing_wait(self):
        from telesale_agent.adapters.llm.rate_limits import ProviderCooldown

        cooldown = ProviderCooldown()
        with patch("telesale_agent.adapters.llm.rate_limits.time.monotonic", return_value=100):
            cooldown.record(RuntimeError("Please try again in 8s."))
            cooldown.record(RuntimeError("Please try again in 2s."))
            self.assertEqual(cooldown.remaining(), 8)
        with patch("telesale_agent.adapters.llm.rate_limits.time.monotonic", return_value=108):
            self.assertEqual(cooldown.remaining(), 0)


if __name__ == "__main__":
    unittest.main()
