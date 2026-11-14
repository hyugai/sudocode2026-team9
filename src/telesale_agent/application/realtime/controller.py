"""Independent native-audio pipeline. Only the event loop owns active turn state."""
import asyncio
import json
import logging
import time
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from telesale_agent.core.models import Channel, ConversationState, CustomerIdentity, TurnContext, TurnInput, Message
from telesale_agent.core.realtime import VoiceTurnRecord, SessionInit
from telesale_agent.application.asr_normalization import normalize_asr_transcript
from telesale_agent.application.conversation.prepare import prepare_context
from telesale_agent.application.memory.coordinator import commit_voice
from telesale_agent.core.history import brief_preview, memory_preview
from telesale_agent.application.tools.protocol import tool_calls_to_steps
from telesale_agent.application.realtime.tool_dispatch import dispatch

logger = logging.getLogger(__name__)


async def initialize_customer(services, conversation_id, phone, customer_id=None):
    started = time.perf_counter()
    state = ConversationState(conversation_id=conversation_id)
    # Session setup is not a customer utterance and does not go through run_turn.
    init = SessionInit(conversation_id, phone)
    context = TurnContext(input=init, state=state)
    if customer_id:
        context.identity = CustomerIdentity(customer_id=customer_id, phone=phone)
    elif services.identity:
        context.identity = await services.identity.resolve_identity(context)
    state.identity = context.identity
    if services.customer_context:
        await services.customer_context.hydrate(context)
    if services.call_brief:
        state.call_brief = await services.call_brief.build_call_brief(context)
        state.call_brief.latency_ms = round((time.perf_counter() - started) * 1000)
    return state, context


async def turn_context(services, state, record, phone, source):
    isolated = deepcopy(state)
    isolated.memory_deltas = {}
    if not isolated.identity or not isolated.identity.customer_id:
        isolated.identity = None
    text = normalize_asr_transcript(record.input_text)
    context = TurnContext(
        input=TurnInput(
            conversation_id=state.conversation_id, text=text, channel=Channel.VOICE,
            customer_hint=phone, metadata={
                "raw_asr_transcript": record.input_text, "memory_source_id": source,
                "call_key": state.conversation_id,
                "call_date": datetime.now(timezone(timedelta(hours=7))).date().isoformat(),
            }),
        state=isolated,
    )
    await prepare_context(services, context)
    context.steps = tool_calls_to_steps(record.tools, actor="Gemini Live")
    context.tool_results = {str(c["id"]): c["result"] for c in record.tools}
    return context


async def recover_memory(services, store):
    """Replay prepared batches or finish pending final turns on the next connection."""
    for job in (await store.pending())[:30]:
        payload = job["payload"]
        if not payload.get("input_finished") or not payload.get("input_text"):
            await store._update(job["source_id"], status="incomplete")
            continue
        try:
            state, _ = await initialize_customer(
                services, payload["conversation_id"], payload.get("phone"), job["customer_id"])
            record = VoiceTurnRecord(input_text=payload["input_text"], input_finished=True,
                                     tools=payload.get("tools", []))
            context = await turn_context(services, state, record, payload.get("phone"), job["source_id"])
            await commit_voice(services, context, store, job["source_id"])
        except Exception:
            logger.exception("Voice memory recovery remains pending: %s", job["source_id"])


class VoiceSessionController:
    def __init__(self, services, settings, model, store, state, initial_context, phone, *, user_id=None):
        self.services, self.settings, self.model, self.store = services, settings, model, store
        self.state, self.initial_context, self.phone = state, initial_context, phone
        self.user_id = user_id
        self.turn_sequence = 0
        self.outbox = asyncio.Queue(maxsize=settings.queue_limit)
        self.generation = 0
        self.current = None
        self.records = {}
        self.pending = {}
        self.jobs = set()
        self.cancelled_calls = set()
        self.tool_results = {}
        self.finalizers = {}
        self.context_locks = {}
        self.closed = False
        self.connected = False
        self.started = time.monotonic()
        self.last_input_at = time.monotonic()
        self.transcript_at = {}
        self.last_audio_at = {}
        self.stop = asyncio.Event()

    async def emit(self, event):
        self.outbox.put_nowait(event)

    def source(self, record):
        return "voice:" + self.state.conversation_id + ":" + record.turn_id

    def active_turn(self):
        if self.current is None or self.current.finalized:
            self.generation += 1
            self.turn_sequence += 1
            self.current = VoiceTurnRecord(generation=self.generation, sequence=self.turn_sequence)
            self.records[self.current.turn_id] = self.current
        return self.current

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.jobs.add(task)
        def done(task):
            self.jobs.discard(task)
            if not task.cancelled() and task.exception():
                logger.error("Voice background operation failed", exc_info=task.exception())
        task.add_done_callback(done)
        return task

    async def interrupt(self):
        old = self.current
        self.generation += 1
        if old:
            old.interrupted = True
            old.model_complete = True
            self.schedule_finalize(old)
        self.current = None
        await self.emit({"type": "interrupted", "generation": self.generation})
        for key, (task, record) in list(self.pending.items()):
            if record is old and not task.done():
                self.cancelled_calls.add(key)
                task.cancel()  # This implementation exposes read-only tools only.

    async def provider_event(self, event):
        content = event.get("server_content") or {}
        # Process control before audio, even when they share a provider event.
        if content.get("interrupted"):
            await self.interrupt()
        cancellation = event.get("tool_call_cancellation") or {}
        for call_id in cancellation.get("ids", []):
            self.cancelled_calls.add(call_id)
            if call_id in self.pending:
                self.pending[call_id][0].cancel()
        interim = content.get("interim_input_transcription")
        if interim and interim.get("text"):
            await self.emit({"type": "transcript_interim", "text": interim["text"]})
        transcript = content.get("input_transcription")
        if transcript and (transcript.get("text") or transcript.get("finished")):
            record = self.active_turn()
            record.transcript(transcript.get("text", ""), finished=bool(transcript.get("finished")))
            self.transcript_at[record.turn_id] = time.monotonic()
            await self.emit({"type": "transcript_update", "role": "user",
                             "turn_id": record.turn_id, "text": record.input_text,
                             "finished": record.input_finished})
        output = content.get("output_transcription")
        if output and output.get("text"):
            record = self.active_turn()
            record.output_text += output["text"]
            await self.emit({"type": "transcript_update", "role": "agent",
                             "turn_id": record.turn_id, "text": record.output_text})
        for part in (content.get("model_turn") or {}).get("parts", []):
            blob = part.get("inline_data") or {}
            if blob.get("data") and not content.get("interrupted"):
                record = self.active_turn()
                self.last_audio_at[record.turn_id] = time.monotonic()
                self.outbox.put_nowait(("audio", record.generation, record.turn_id, blob["data"]))
        calls = (event.get("tool_call") or {}).get("function_calls", [])
        for call in calls:
            record = self.active_turn()
            call_id = call.get("id") or ""
            if call_id in self.pending or call_id in self.cancelled_calls:
                continue
            if call_id in self.tool_results:
                name, result = self.tool_results[call_id]
                self.spawn(self.model.tool_result(call_id, name, result))
                continue
            task = self.spawn(self.call_tool(record, call))
            self.pending[call_id] = (task, record)
        if content.get("turn_complete"):
            record = self.current
            status = content.get("interaction_status", "IDLE")
            status = getattr(status, "value", status)
            if record and status != "IN_PROGRESS":
                record.model_complete = True
                self.schedule_finalize(record)
        if event.get("usage_metadata"):
            await self.emit({"type": "usage", "usage": event["usage_metadata"]})
        if event.get("go_away"):
            raise ConnectionError("Provider requested reconnection")

    async def context_for(self, record, *, stable_read=False):
        lock = self.context_locks.setdefault(record.turn_id, asyncio.Lock())
        async with lock:
            return await self.prepare_record(record, stable_read=stable_read)

    async def prepare_record(self, record, *, stable_read=False):
        revision = record.revision
        if record.context and record.prepared_revision == revision:
            return record.context
        if not record.input_finished and not stable_read:
            return None
        context = await turn_context(self.services, self.state, record, self.phone, self.source(record))
        if record.revision != revision:
            return None
        record.context, record.prepared_revision = context, revision
        return context

    async def call_tool(self, record, call):
        call_id, name = call.get("id", ""), call.get("name", "")
        try:
            # Keep model receive loop alive while waiting for final transcription.
            for _ in range(10):
                if record.input_finished or record.interrupted:
                    break
                if record.input_text and time.monotonic() - self.transcript_at.get(record.turn_id, 0) >= .4:
                    break
                await asyncio.sleep(.1)
            context = await self.context_for(record, stable_read=bool(record.input_text))
            if record.interrupted or call_id in self.cancelled_calls:
                return
            result, evidence = await dispatch(
                self.services, self.settings, context.state if context else self.state, context or (
                    self.initial_context if name == "get_customer_context" else None),
                name, call.get("args") or {}, call_id)
            if evidence:
                record.tools.append(evidence)
            if call_id not in self.cancelled_calls and not record.interrupted:
                self.tool_results[call_id] = (name, result)
                await self.model.tool_result(call_id, name, result)
            await self.emit({"type": "operation_update", "name": name,
                             "status": "failed" if result.get("error") else "completed"})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Voice read tool failed")
            if not record.interrupted and call_id not in self.cancelled_calls:
                await self.model.tool_result(call_id, name, {"error": "tool_failed"})
        finally:
            self.pending.pop(call_id, None)

    def schedule_finalize(self, record):
        if record.turn_id not in self.finalizers:
            self.finalizers[record.turn_id] = self.spawn(self.finalize(record))

    async def finalize(self, record):
        # Quiet period accommodates final transcript arriving after turn_complete.
        await asyncio.sleep(.5)
        while time.monotonic() - self.transcript_at.get(record.turn_id, 0) < .4:
            await asyncio.sleep(.1)
        tasks = [task for task, turn in list(self.pending.values()) if turn is record]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Non-interim input_transcription is accepted at a completed interaction.
        # A disconnect alone must not promote an unfinished transcript.
        if record.model_complete and not record.interrupted and record.input_text:
            record.input_finished = True
        record.finalized = True
        payload = {
            "conversation_id": self.state.conversation_id, "phone": self.phone,
            "user_id": self.user_id, "turn_number": record.sequence, "created_at": record.created_at,
            "input_text": record.input_text, "input_finished": record.input_finished,
            "output_text": record.output_text, "interrupted": record.interrupted,
            "played_samples": record.played_samples, "tools": record.tools,
        }
        customer = self.state.identity.customer_id if self.state.identity else None
        source = self.source(record)
        try:
            await self.store.save(source, customer, payload,
                                  status="pending" if record.input_finished else "incomplete")
            if not record.input_finished:
                return
            context = await self.context_for(record)
            if context:
                context.steps = tool_calls_to_steps(record.tools, actor="Gemini Live")
                context.tool_results = {str(c["id"]): c["result"] for c in record.tools}
                if context.identity:
                    self.state.identity = context.identity
                await commit_voice(self.services, context, self.store, source)
                self.state.customer_memory = context.state.customer_memory
                self.state.turn_number += 1
                self.state.messages.extend([
                    Message("customer", context.input.text),
                    Message("agent", record.output_text + (" [bị ngắt]" if record.interrupted else "")),
                ])
                self.state.messages = self.state.messages[-20:]
                if self.services.call_brief:
                    self.state.call_brief = await self.services.call_brief.build_call_brief(context)
                # Projection-only update: never reset journal status or prepared memory jobs.
                await self.store.save_snapshot(source, brief_preview(self.state.call_brief), memory_preview(context.state))
                await self.emit({"type": "memory_committed", "turn_id": record.turn_id})
        except Exception:
            logger.exception("Voice memory job pending: %s", source)
            if not self.closed:
                await self.emit({"type": "memory_pending", "turn_id": record.turn_id})

    async def model_loop(self):
        retries = 0
        while not self.closed:
            try:
                async for event in self.model.events():
                    await self.provider_event(event)
                if not self.closed:
                    raise ConnectionError("Live connection closed")
            except asyncio.CancelledError:
                raise
            except Exception:
                if self.closed or retries >= 2:
                    raise
                retries += 1
                self.connected = False
                await self.interrupt()
                await self.emit({"type": "connection", "status": "reconnecting"})
                await asyncio.sleep(retries)
                from telesale_agent.application.realtime.context import instructions
                self.model.instructions = instructions(self.state)
                await self.model.reconnect()
                self.connected = True
                await self.emit({"type": "connection", "status": "connected"})

    async def client_loop(self, websocket):
        while not self.closed:
            message = await asyncio.wait_for(websocket.receive(), self.settings.idle_seconds)
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                data = message["bytes"]
                if not data or len(data) % 2 or len(data) > 6400:
                    raise ValueError("Invalid PCM audio frame")
                self.last_input_at = time.monotonic()
                if self.connected:
                    await self.model.audio(data)
            elif message.get("text"):
                if len(message["text"]) > 2048:
                    raise ValueError("Control message too large")
                control = json.loads(message["text"])
                kind = control.get("type")
                if kind == "close":
                    return
                if kind == "input_started" and self.current and self.current.model_complete:
                    self.schedule_finalize(self.current)
                    self.current = None
                if kind == "input_audio_end" and self.connected:
                    await self.model.audio_end()
                elif kind == "playback_progress":
                    record = self.records.get(control.get("turn_id"))
                    samples = control.get("samples")
                    if record and type(samples) is int and 0 <= samples <= 24000 * self.settings.session_seconds:
                        record.played_samples = max(record.played_samples, samples)
                elif kind == "interrupt":
                    await self.interrupt()

    async def sender(self, websocket):
        while True:
            item = await self.outbox.get()
            if isinstance(item, tuple):
                _, generation, turn_id, audio = item
                if generation != self.generation:
                    continue
                await websocket.send_json({"type": "audio", "generation": generation,
                                           "turn_id": turn_id, "sample_rate": 24000})
                await websocket.send_bytes(audio)
            else:
                await websocket.send_json(item)

    async def run(self, websocket):
        tasks = []
        try:
            await self.model.open()
            self.connected = True
            await self.emit({"type": "session_ready", "model": self.settings.model,
                             "mode": "read_only", "input_sample_rate": 16000, "output_sample_rate": 24000})
            tasks = [asyncio.create_task(self.model_loop()), asyncio.create_task(self.client_loop(websocket)),
                     asyncio.create_task(self.sender(websocket)), asyncio.create_task(self.stop.wait())]
            done, _ = await asyncio.wait(tasks, timeout=self.settings.session_seconds,
                                         return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            self.closed = True
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for task, _ in list(self.pending.values()):
                task.cancel()
            if self.current and not self.current.finalized:
                self.schedule_finalize(self.current)
            if self.jobs:
                # Backend persistence must finish independently of playback/disconnect.
                await asyncio.gather(*list(self.jobs), return_exceptions=True)
            await self.model.close()
