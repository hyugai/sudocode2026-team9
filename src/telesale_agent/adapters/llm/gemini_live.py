"""Google-specific Live I/O. Lazy import keeps offline/text installations working."""
import asyncio
import os


class GeminiLiveClient:
    def __init__(self, settings, instructions, tools):
        self.settings, self.instructions, self.tools = settings, instructions, tools
        self.session = None
        self.client = None
        self.connection = None
        self.resume_handle = None
        self.lock = asyncio.Lock()

    async def open(self):
        from google import genai
        key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Thiếu GOOGLE_API_KEY hoặc GEMINI_API_KEY ở backend")
        if self.client is None:
            self.client = genai.Client(api_key=key, http_options={"api_version": self.settings.api_version})
        config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": self.instructions,
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "speech_config": {"voice_config": {"prebuilt_voice_config": {
                "voice_name": self.settings.voice}}},
            "context_window_compression": {
                "trigger_tokens": 12000, "sliding_window": {"target_tokens": 4000}},
            "session_resumption": {"handle": self.resume_handle},
        }
        if self.tools:
            config["tools"] = [{"function_declarations": self.tools}]
        # gemini-3.8-live does not accept thinking_level/config, proactive_audio=False,
        # or enable_affective_dialog. Do not inherit text-model thinking settings.
        self.connection = self.client.aio.live.connect(model=self.settings.model, config=config)
        try:
            self.session = await asyncio.wait_for(self.connection.__aenter__(), timeout=20)
        except BaseException:
            self.connection = None
            raise

    async def audio(self, data):
        from google.genai import types
        async with self.lock:
            if self.session:
                await self.session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))

    async def audio_end(self):
        async with self.lock:
            if self.session:
                await self.session.send_realtime_input(audio_stream_end=True)

    async def tool_result(self, call_id, name, result):
        from google.genai import types
        async with self.lock:
            if self.session:
                await self.session.send_tool_response(function_responses=[
                    types.FunctionResponse(id=call_id, name=name, response=result)])

    async def events(self):
        while self.session:
            # SDK receive() ends at an interaction boundary, not at session end.
            async for message in self.session.receive():
                if message.session_resumption_update:
                    update = message.session_resumption_update
                    if update.resumable and update.new_handle:
                        self.resume_handle = update.new_handle
                yield message.model_dump(exclude_none=True, mode="python")

    async def reconnect(self):
        async with self.lock:
            await self._disconnect()
            try:
                await self.open()
            except Exception:
                if not self.resume_handle:
                    raise
                self.resume_handle = None
                await self.open()

    async def _disconnect(self):
        self.session = None
        if self.connection:
            connection, self.connection = self.connection, None
            await connection.__aexit__(None, None, None)

    async def close(self):
        async with self.lock:
            try:
                await self._disconnect()
            finally:
                if self.client:
                    await self.client.aio.aclose()
                    self.client = None
