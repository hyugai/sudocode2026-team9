"""Post-session learning, shared by the API and the standalone wrapper."""
import asyncio
import json
import logging
import time
import traceback
from types import SimpleNamespace

from self_agent.adapters.agent_memory import AgentMemory
from self_agent.config import LearningConfig
from self_agent.models import LearningJob, digest, sanitize, snapshot

logger = logging.getLogger(__name__)


class SelfLearningService:
    def __init__(self, *, config=None, memory=None, repository=None, learner_factory=None, search=None):
        self.config = config if config is not None else LearningConfig.from_env()
        self.memory, self.repository = memory, repository
        self.learner_factory, self.search = learner_factory, search
        self.learner = self.worker = None
        self.lock = asyncio.Lock()
        self.wakeup = asyncio.Event()
        self.closing = False
        self.voice_recovery = None
        self.lease = None
        self.pending_guest = {}
        self.next_voice_recovery = 0

    def _memory(self):
        if self.memory is None:
            self.memory = AgentMemory(self.config.root, runtime_root=self.config.runtime_root)
        return self.memory

    async def start(self):
        if not self.config.enabled or self.repository is None:
            return
        await asyncio.to_thread(self.repository.ready)
        if self.repository.engine.dialect.name == "postgresql":
            from sqlalchemy import text
            def acquire():
                connection = self.repository.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
                try:
                    if not connection.execute(text("SELECT pg_try_advisory_lock(1826417822)")).scalar():
                        raise RuntimeError("Self-learning yêu cầu một backend worker")
                    return connection
                except BaseException:
                    connection.close()
                    raise
            self.lease = await asyncio.to_thread(acquire)
        try:
            await asyncio.to_thread(self.repository.recover_jobs)
            # Active voice sessions cannot reconnect across backend processes.
            # Their persisted journal is recovered before their learning job.
            from sqlalchemy import update
            from telesale_agent.adapters.db.learning import sessions, now
            def recover_voice():
                with self.repository.engine.begin() as connection:
                    connection.execute(update(sessions).where(
                        sessions.c.channel == "voice", sessions.c.status == "active").values(
                            status="finalizing", updated_at=now()))
            await asyncio.to_thread(recover_voice)
            self.worker = asyncio.create_task(self._work(), name="self-learning")
        except BaseException:
            await self.close()
            raise

    async def end_session(self, state, *, turn_results=(), feedback=()):
        """Compatibility API for local runners. Backend uses transactional hooks."""
        if not self.config.enabled:
            return LearningJob("disabled")
        async with self.lock:
            try:
                data = snapshot(state, turn_results, feedback)
                key = digest(data)
                memory = self._memory()
                try:
                    job = await asyncio.to_thread(memory.read, "jobs", key)
                except FileNotFoundError:
                    job = {"id": key, "status": "queued", "attempts": 0, "snapshot": data}
                    await asyncio.to_thread(memory.write, "jobs", key, job)
                if self.worker is None or self.worker.done():
                    self.worker = asyncio.create_task(self._work())
                return LearningJob(job["status"], key)
            except (OSError, ValueError) as exc:
                return LearningJob("enqueue_failed", error=type(exc).__name__)

    def capture_turn(self, state, result):
        """Capture only this turn; durable rows retain the complete conversation."""
        turn_state = SimpleNamespace(
            conversation_id=state.conversation_id, turn_number=state.turn_number,
            identity=state.identity, call_brief=state.call_brief, messages=state.messages[-2:])
        turn_state.customer_profile = getattr(state, "customer_profile", {})
        evidence = SimpleNamespace(
            turn_number=state.turn_number, response_text=result.response_text,
            retrieved=getattr(result, "retrieved", None), tool_calls=getattr(result, "tool_calls", []))
        data = snapshot(turn_state, [evidence])
        return {"messages": data.pop("messages"), "evidence": data.pop("turn_evidence")[0]}, data

    def capture_voice_turn(self, state, payload):
        identity = state.identity
        profiles = [getattr(identity, "profile", None) or {}, getattr(state, "customer_profile", None) or {}]
        secrets = [getattr(identity, "phone", None), payload.get("phone"),
                   *[profile.get(k) for profile in profiles for k in ("name", "address", "phone", "email")]]
        answer = sanitize(payload.get("output_text", ""), secrets)
        output_complete = payload.get("output_complete", not payload.get("interrupted", False))
        if not output_complete:
            answer += " [câu trả lời chưa hoàn tất hoặc bị ngắt]"
        return {"messages": [{"role": "customer", "content": sanitize(payload.get("input_text", ""), secrets)},
                             {"role": "agent", "content": answer}],
                "evidence": {"agent_response": answer, "tool_calls": sanitize(payload.get("tools", []), secrets),
                             "sources": [], "promotions": [], "interrupted": bool(payload.get("interrupted")),
                             "output_complete": bool(output_complete),
                             "played_samples": payload.get("played_samples", 0)}}

    def save_hook(self, channel, state, result, *, checkpoint=None):
        payload, context = self.capture_turn(state, result)
        conversation_id, number = state.conversation_id, state.turn_number
        def save(connection):
            self.repository.save_turn(connection, channel, conversation_id,
                                      number, payload, context, checkpoint)
        return save

    async def save_guest(self, state, result):
        from telesale_agent.adapters.db.checkpoint import serialize_checkpoint
        hook = self.save_hook("guest", state, result, checkpoint=serialize_checkpoint(state))
        self.pending_guest.setdefault(state.conversation_id, []).append(hook)
        await self.flush_guest(state.conversation_id)

    async def flush_guest(self, conversation_id):
        hooks = self.pending_guest.get(conversation_id, [])
        if hooks:
            def save():
                with self.repository.engine.begin() as connection:
                    for hook in hooks:
                        hook(connection)
            await asyncio.to_thread(save)
            self.pending_guest.pop(conversation_id, None)

    async def restore_guest(self, conversation_id):
        from telesale_agent.adapters.db.learning import session_key
        from telesale_agent.adapters.db.checkpoint import deserialize_checkpoint
        row = await asyncio.to_thread(self.repository.get_session, session_key("guest", conversation_id))
        if row and row["status"] == "ended":
            raise ValueError("Phiên đã kết thúc. Hãy bắt đầu phiên mới.")
        return deserialize_checkpoint(row["checkpoint"]) if row and row["checkpoint"] else None

    def queue_in_transaction(self, connection, channel, state, *, messages=None, feedback=()):
        from telesale_agent.adapters.db.learning import session_key
        key = session_key(channel, state.conversation_id)
        row = self.repository.get_session(key, connection)
        if row and row["status"] == "ended":
            from sqlalchemy import select
            from telesale_agent.adapters.db.learning import jobs
            return dict(connection.execute(select(jobs).where(jobs.c.session_id == key)).mappings().one())
        # Empty state is only a source of current questions and redaction hints;
        # the authoritative history is supplied by DB/journal, never tail RAM.
        base = SimpleNamespace(conversation_id=state.conversation_id, identity=state.identity,
                               customer_profile=getattr(state, "customer_profile", {}),
                               turn_number=state.turn_number, call_brief=state.call_brief, messages=[])
        data = snapshot(base, feedback=feedback)
        self.repository.ensure(connection, channel, state.conversation_id, data)
        records = self.repository.read_turns(connection, key)
        history = messages if messages is not None else [m for r in records for m in r["messages"]]
        identity = state.identity
        profiles = [getattr(identity, "profile", None) or {}, getattr(state, "customer_profile", None) or {}]
        secrets = [getattr(identity, "phone", None),
                   *[profile.get(k) for profile in profiles for k in ("name", "address", "phone", "email")]]
        data["messages"] = [{"message_id": i, "role": m["role"], "content": sanitize(m["content"], secrets)}
                            for i, m in enumerate(history)]
        data["turn_evidence"] = [r["evidence"] for r in records if r.get("evidence")]
        count = sum(m["role"] in {"user", "customer"} for m in data["messages"])
        data["revision"] = count
        data["evidence_coverage"] = ("per_turn_evidence" if len(data["turn_evidence"]) == count else
                                     "partial_turn_evidence" if data["turn_evidence"] else "transcript_only")
        if len(json.dumps(data, ensure_ascii=False).encode()) > 512_000:
            from telesale_agent.adapters.db.learning import LearningSnapshotTooLarge
            raise LearningSnapshotTooLarge("Dữ liệu học vượt giới hạn 512 KB. Phiên vẫn được giữ; liên hệ quản trị để xử lý.")
        job_id = digest([channel, data["session"], count, data["workflow_version"]])
        return self.repository.queue(connection, key, data, job_id)

    async def end_guest(self, state):
        await self.flush_guest(state.conversation_id)
        def end():
            with self.repository.engine.begin() as connection:
                return self.queue_in_transaction(connection, "guest", state)
        result = await asyncio.to_thread(end)
        self.wakeup.set()
        return LearningJob(result["status"], result["id"])

    async def register_voice(self, state):
        data = snapshot(SimpleNamespace(conversation_id=state.conversation_id, turn_number=0,
                                       identity=state.identity, customer_profile=getattr(state, "customer_profile", {}),
                                       call_brief=state.call_brief, messages=[]))
        def register():
            with self.repository.engine.begin() as connection:
                self.repository.ensure(connection, "voice", state.conversation_id, data)
        await asyncio.to_thread(register)

    async def finalize_voice(self, state):
        from sqlalchemy import update
        from telesale_agent.adapters.db.learning import sessions, session_key, now
        context = snapshot(SimpleNamespace(conversation_id=state.conversation_id, identity=state.identity,
                                            customer_profile=getattr(state, "customer_profile", {}),
                                            turn_number=state.turn_number, call_brief=state.call_brief, messages=[]))
        def mark():
            with self.repository.engine.begin() as connection:
                connection.execute(update(sessions).where(
                    sessions.c.id == session_key("voice", state.conversation_id),
                    sessions.c.status != "ended").values(status="finalizing", context=context, updated_at=now()))
        await asyncio.to_thread(mark)
        self.next_voice_recovery = 0
        self.wakeup.set()

    async def wait_learning(self, job_id):
        if self.worker and self.repository is None:
            await self.worker
        if self.memory is None:
            return LearningJob("disabled")
        job = await asyncio.to_thread(self.repository.get_job, job_id) if self.repository else await asyncio.to_thread(
            self.memory.read, "jobs", job_id)
        return LearningJob(job["status"], job_id, job.get("error"))

    def _learner(self):
        if self.learner is None:
            if self.learner_factory:
                self.learner = self.learner_factory(self._memory())
            else:
                from self_agent.adapters.llm import LearningModel
                from self_agent.learning.knowledge_gap import KnowledgeGapLoop
                self.learner = KnowledgeGapLoop(self._memory(), LearningModel(), self.search)
        return self.learner

    async def _process(self, job):
        started = time.perf_counter()
        error = None
        try:
            if self.repository is not None and not job["snapshot"].get("messages"):
                report = {"job_id": job["id"], "outcome": "empty_session", "gaps": []}
                await asyncio.to_thread(self._memory().write, "reports", job["id"], report)
            else:
                report = await self._learner().process(job["id"], job["snapshot"])
            if isinstance(report, dict) and report.get("detector_error"):
                error = report["detector_error"]
        except asyncio.CancelledError:
            # Running DB jobs are requeued on next startup. File jobs retain
            # the standalone runner's immediate recovery behavior.
            if self.repository is None:
                job.update(status="queued", attempts=job["attempts"] - 1)
                await asyncio.to_thread(self.memory.write, "jobs", job["id"], job)
            raise
        except Exception as exc:
            error = type(exc).__name__
            if self.repository is None:
                job["error_details"] = [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                                        for frame in traceback.extract_tb(exc.__traceback__)]
        if self.repository:
            await asyncio.to_thread(self.repository.finish, job, error, self.config.max_attempts)
        else:
            job.update(status="failed" if error else "done", error=error)
            await asyncio.to_thread(self.memory.write, "jobs", job["id"], job)
        logger.info("Learning job=%s attempt=%s error=%s duration_ms=%s", job["id"], job["attempts"],
                    error, round((time.perf_counter() - started) * 1000))

    async def _work(self):
        while not self.closing:
            if self.repository is None:
                pending = [j for j in await asyncio.to_thread(self.memory.records, "jobs")
                           if j["status"] != "done" and j["attempts"] < self.config.max_attempts]
                if not pending:
                    return
                for job in pending:
                    while job["status"] != "done" and job["attempts"] < self.config.max_attempts:
                        job.update(status="running", attempts=job["attempts"] + 1)
                        await asyncio.to_thread(self.memory.write, "jobs", job["id"], job)
                        await self._process(job)
                continue
            try:
                self.wakeup.clear()
                if self.voice_recovery and time.monotonic() >= self.next_voice_recovery:
                    self.next_voice_recovery = time.monotonic() + 30
                    await self.voice_recovery()
                job = await asyncio.to_thread(self.repository.claim, self.config.max_attempts)
                if job:
                    await self._process(job)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Learning worker error=%s", type(exc).__name__)
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=1)
            except TimeoutError:
                pass

    async def close(self):
        self.closing = True
        if self.worker and not self.worker.done():
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
        # Retain any completed guest turn that was waiting for a DB retry.
        # Failure leaves the API's outcome-unknown semantics intact.
        for conversation_id in list(self.pending_guest):
            try:
                await self.flush_guest(conversation_id)
            except Exception as exc:
                logger.warning("Guest learning shutdown persistence error=%s", type(exc).__name__)
        if self.lease:
            from sqlalchemy import text
            connection, self.lease = self.lease, None
            def release():
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(1826417822)"))
                finally:
                    connection.close()
            await asyncio.to_thread(release)
