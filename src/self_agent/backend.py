"""API composition root: database jobs, object lessons, and Chat-only routing."""
import asyncio
import logging
import os
from types import SimpleNamespace

from sqlalchemy import inspect, select

from self_agent.config import LearningConfig
from self_agent.lesson_runtime import CURRENT_LESSONS, LessonAgent
from self_agent.lessons import LessonRouter
from self_agent.models import digest, sanitize, snapshot
from self_agent.service import SelfLearningService
from telesale_agent.adapters.db.learning import LearningRepository, sessions, session_key

logger = logging.getLogger(__name__)


class BackendLearning(SelfLearningService):
    def __init__(self, base, *, engine, memory, config, routing_model=None, learner_factory=None):
        async def search(question):
            from telesale_agent.application.deepagent.tools.protocol import decode_tool_result
            return decode_tool_result(await base.mcp_tools["search_policy"].ainvoke({"query": question}))
        super().__init__(config=config, memory=memory, repository=LearningRepository(engine),
                         learner_factory=learner_factory, search=search)
        self.base = base
        self.original_agent = None
        self.routing_model = routing_model
        self.voice_recovery = self.recover_voice

    async def start(self):
        if not self.config.enabled:
            return
        if os.getenv("DEEPAGENT_CHECKPOINT_SCOPE", "turn").strip().lower() == "conversation":
            raise ValueError("Self-learning Chat routing requires per-turn checkpoints")
        await super().start()
        if getattr(self.base, "agent", None) is not None:
            self.original_agent = self.base.agent
            self.base.agent = LessonAgent(self.base.agent)

    async def begin_chat(self, channel, turn_input, state):
        """Freeze a bank per conversation; ContextVar isolates concurrent calls."""
        trace = {"mode": "memory_only", "response_modified": False, "selected_lessons": [], "injected": False}
        bank = []
        try:
            key = session_key(channel, state.conversation_id)
            def ensure():
                with self.repository.engine.begin() as connection:
                    data = snapshot(SimpleNamespace(conversation_id=state.conversation_id, identity=state.identity,
                                                     call_brief=state.call_brief, turn_number=0, messages=[]))
                    self.repository.ensure(connection, channel, state.conversation_id, data)
                    row = self.repository.get_session(key, connection)
                    if row["status"] != "active":
                        raise ValueError("Phiên đã kết thúc. Hãy bắt đầu phiên mới.")
                    return row
            row = await asyncio.to_thread(ensure)
            bank = row["lessons"]
            if bank is None:
                try:
                    bank = await asyncio.to_thread(self.memory.load_lessons)
                except Exception as exc:
                    logger.warning("Learning bank unavailable error=%s", type(exc).__name__)
                    trace["bank_error"] = type(exc).__name__
                    bank = []
                bank = await asyncio.to_thread(self.repository.freeze_lessons, key, bank)
            trace["lessons_loaded"] = len(bank)
        except Exception as exc:
            # Lesson storage/routing is optional; saving completed turns and
            # the terminal job remains strict in the API transaction.
            trace.update(routing="failed", routing_error=type(exc).__name__)
            logger.warning("Learning routing error=%s", type(exc).__name__)
        turn_input.metadata["lesson_trace"] = trace
        async def route(context):
            try:
                if bank:
                    if self.routing_model is None:
                        from self_agent.adapters.llm import LearningModel
                        self.routing_model = LearningModel()
                    identity = state.identity
                    profiles = [getattr(identity, "profile", None) or {}, getattr(state, "customer_profile", None) or {}]
                    secrets = [getattr(identity, "phone", None),
                               *[profile.get(k) for profile in profiles for k in ("name", "address", "phone", "email")]]
                    history = [{"role": m.role, "content": m.content} for m in state.messages[-4:]]
                    context["lessons"] = await LessonRouter(bank).select(
                        sanitize(turn_input.text or "", secrets), model=self.routing_model,
                        history=sanitize(history, secrets))
                trace["routing"] = "selected" if context["lessons"] else "no_match"
                trace["selected_lessons"] = [{"id": card["id"], "hash": digest(card)} for card in context["lessons"]]
            except Exception as exc:
                trace.update(routing="failed", routing_error=type(exc).__name__)
                logger.warning("Learning routing error=%s", type(exc).__name__)
        context = {"lessons": [], "trace": trace, "prepare": route}
        # File audio has no transcript yet. LessonAgent prepares routing just
        # before generation, after the existing harness has run ASR.
        if not turn_input.audio:
            await route(context)
            context["prepared"] = True
        return CURRENT_LESSONS.set(context)

    @staticmethod
    def reset_chat(token):
        CURRENT_LESSONS.reset(token)

    async def recover_voice(self):
        """Only terminal sessions are replayed; active Live calls keep ownership."""
        from telesale_agent.adapters.db.voice_store import VoiceStore, turns as journal
        from telesale_agent.application.conversation.services import ConversationServices
        from telesale_agent.application.realtime.controller import recover_memory

        def pending():
            with self.repository.engine.connect() as connection:
                schema = self.repository.engine.get_execution_options().get("schema_translate_map", {}).get(None)
                if not inspect(connection).has_table(journal.name, schema=schema):
                    return []
                return [dict(row) for row in connection.execute(select(sessions).where(
                    sessions.c.channel == "voice", sessions.c.status == "finalizing").limit(30)).mappings()]
        for session in await asyncio.to_thread(pending):
            try:
                store = VoiceStore(self.repository.engine)
                await recover_memory(ConversationServices.from_harness(self.base), store,
                                     conversation_id=session["conversation_id"])
                def queue():
                    with self.repository.engine.begin() as connection:
                        rows = list(connection.execute(select(journal).where(
                            journal.c.payload["conversation_id"].as_string() == session["conversation_id"]
                        )).mappings())
                        if any(row["status"] in {"pending", "prepared"} for row in rows):
                            return
                        context = session["context"]
                        state = SimpleNamespace(conversation_id=session["conversation_id"], identity=None,
                                                call_brief=SimpleNamespace(open_questions=context.get("open_questions", [])),
                                                turn_number=0, messages=[])
                        # Sequence is the source ordering; compact IDs for the
                        # learner stay aligned even when incomplete input is omitted.
                        count = 0
                        for row in sorted(rows, key=lambda r: r["payload"].get("turn_number", 0)):
                            payload = row["payload"]
                            if not payload.get("input_finished") or not payload.get("input_text"):
                                continue
                            count += 1
                            # New journals capture redaction hints while identity
                            # is available. Old journals have no learning record
                            # and are outside this feature's session registration.
                            record = payload.get("learning")
                            if record is None:
                                raise ValueError("Voice journal lacks redacted learning evidence")
                            record = {**record, "evidence": {**record["evidence"], "turn_id": count}}
                            self.repository.save_turn(connection, "voice", state.conversation_id,
                                                      count, record, context)
                        self.queue_in_transaction(connection, "voice", state)
                await asyncio.to_thread(queue)
            except Exception as exc:
                logger.warning("Voice learning recovery session=%s error=%s", session["id"], type(exc).__name__)

    async def close(self):
        try:
            await super().close()
        finally:
            if self.original_agent is not None:
                self.base.agent = self.original_agent
                self.original_agent = None


async def build_backend_learning(base, engine):
    config = LearningConfig.from_env()
    if not config.enabled:
        return None
    from self_agent.adapters.object_memory import ObjectStorageAgentMemory
    service = BackendLearning(base, engine=engine, memory=ObjectStorageAgentMemory(), config=config)
    await service.start()
    return service
