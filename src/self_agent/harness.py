"""Composition facade. The existing harness and benchmark never import this."""
import asyncio
import traceback
import time
from .config import LearningConfig
from .models import LearningJob, digest, snapshot, sanitize


class SelfAgentHarness:
    def __init__(self, base, *, config=None, learner_factory=None, lessons=None, validation_model=None, routing_model=None):
        self.base = base
        self.config = config if config is not None else LearningConfig.from_env()
        self.learner_factory = learner_factory
        self.memory = self.learner = self.worker = None
        self.lock = asyncio.Lock()
        from .lessons import LessonRouter, load_bank
        self.auto_memory=lessons is None and self.config.enabled
        self.lesson_router = LessonRouter((load_bank(self.config.root) if self.auto_memory else lessons or ()) if self.config.enabled else ())
        self.validation_model = routing_model or validation_model
        self.lesson_traces = {}
        self.started_sessions=set()
        self.wrapper_installed=False
        self.original_agent = None

    async def __aenter__(self):
        import os
        if self.lesson_router.lessons and os.getenv('DEEPAGENT_CHECKPOINT_SCOPE', 'turn') == 'conversation':
            raise ValueError('Scoped lesson routing requires per-turn checkpoints, not conversation checkpoints')
        await self.base.__aenter__()
        if self.lesson_router.lessons or self.auto_memory and hasattr(self.base,'agent'):
            from .lesson_runtime import LessonAgent
            self.original_agent = self.base.agent
            self.base.agent = LessonAgent(self.base.agent)
            self.wrapper_installed=True
        return self

    async def run_turn(self, turn_input, state=None, *, on_text=None, on_status=None):
        if self.auto_memory and turn_input.conversation_id not in self.started_sessions:
            from .lessons import LessonRouter,load_bank
            self.lesson_router=LessonRouter(load_bank(self.config.root))
            self.started_sessions.add(turn_input.conversation_id)
        if not self.lesson_router.lessons:
            return await self.base.run_turn(turn_input, state, on_text=on_text, on_status=on_status)
        from .lesson_runtime import CURRENT_LESSONS
        from .models import digest
        if self.validation_model is None:
            from .adapters.llm import LearningModel
            self.validation_model = LearningModel()
        trace = {'lessons_loaded': len(self.lesson_router.lessons), 'selected_lessons': [],
                 'injected': False, 'mode':'memory_only','response_modified':False,'routing': 'no_match'}
        started = time.perf_counter()
        usage_before = dict(getattr(self.validation_model, 'usage', {}))
        history = [{'role': m.role, 'content': m.content}
                   for m in (getattr(state, 'messages', []) or [])[-4:]]
        identity = getattr(state, 'identity', None)
        profile = getattr(identity, 'profile', None) or {}
        secrets = [getattr(identity, 'phone', None),
                   *[profile.get(k) for k in ('name', 'address', 'phone', 'email')]]
        try:
            lessons = await self.lesson_router.select(sanitize(turn_input.text or '', secrets),
                model=self.validation_model, history=sanitize(history, secrets))
            trace['routing'] = 'selected' if lessons else 'no_match'
        except Exception as exc:
            lessons = []
            trace.update(routing='failed', routing_error=type(exc).__name__)
        trace.update(routing_ms=round((time.perf_counter() - started) * 1000, 3),
                     routing_usage={k: v - usage_before.get(k, 0)
                                    for k, v in getattr(self.validation_model, 'usage', {}).items()},
                     selected_lessons=[{'id': l['id'], 'hash': digest(l), 'mechanism': l.get('mechanism','knowledge_gap')} for l in lessons])
        token = CURRENT_LESSONS.set({'lessons': lessons, 'question': sanitize(turn_input.text, secrets),
                                    'trace': trace})
        try:
            result = await self.base.run_turn(turn_input, state, on_text=on_text, on_status=on_status)
            trace['wrapper_total_ms'] = round((time.perf_counter() - started) * 1000, 3)
            self.lesson_traces.setdefault(result.conversation_id, []).append(trace)
            return result
        finally:
            CURRENT_LESSONS.reset(token)

    async def end_session(self, state, *, turn_results=(), feedback=()):
        if not self.config.enabled:
            return LearningJob("disabled")
        async with self.lock:
            try:
                from .adapters.agent_memory import AgentMemory
                if self.memory is None:
                    self.memory = AgentMemory(self.config.root, runtime_root=self.config.runtime_root)
                data = snapshot(state, turn_results, feedback)
                key = digest(data)
                try:
                    job = self.memory.read("jobs", key)
                except FileNotFoundError:
                    job = {"id": key, "status": "queued", "attempts": 0, "snapshot": data}
                    await asyncio.to_thread(self.memory.write, "jobs", key, job)
                if self.worker is None or self.worker.done():
                    self.worker = asyncio.create_task(self._work())
                return LearningJob(job["status"], key)
            except (OSError, ValueError) as exc:
                return LearningJob("enqueue_failed", error=str(exc))

    async def _work(self):
        if self.learner is None:
            if self.learner_factory:
                self.learner = self.learner_factory(self.memory)
            else:
                from .adapters.llm import LearningModel
                from .learning.knowledge_gap import KnowledgeGapLoop
                async def search(question):
                    from telesale_agent.application.deepagent.tools.protocol import decode_tool_result
                    return decode_tool_result(await self.base.mcp_tools["search_policy"].ainvoke({"query": question}))
                self.learner = KnowledgeGapLoop(self.memory, LearningModel(), search)
        while True:
            pending = [j for j in self.memory.records("jobs")
                       if j["status"] != "done" and j["attempts"] < self.config.max_attempts]
            if not pending:
                return
            await self._process_jobs(pending)

    async def _process_jobs(self, pending):
        for job in pending:
            while job["status"] != "done" and job["attempts"] < self.config.max_attempts:
                job.update(status="running", attempts=job["attempts"] + 1)
                self.memory.write("jobs", job["id"], job)
                try:
                    report = await self.learner.process(job["id"], job["snapshot"])
                    if isinstance(report, dict) and report.get("detector_error"):
                        job.update(status="failed", error=report["detector_error"])
                    else:
                        job.update(status="done", error=None)
                except asyncio.CancelledError:
                    job["status"] = "queued"
                    job["attempts"] -= 1
                    self.memory.write("jobs", job["id"], job)
                    raise
                except Exception as exc:
                    job.update(status="failed", error=type(exc).__name__)
                    # Keep code locations, not provider payloads/credentials or
                    # transcript-bearing exception messages, in diagnostics.
                    job["error_details"] = [
                        {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                        for frame in traceback.extract_tb(exc.__traceback__)]
                self.memory.write("jobs", job["id"], job)

    async def wait_learning(self, job_id):
        if self.worker:
            await self.worker
        if self.memory is None:
            return LearningJob("disabled")
        job = self.memory.read("jobs", job_id)
        return LearningJob(job["status"], job_id, job.get("error"))

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self.worker and not self.worker.done():
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
        if self.wrapper_installed:
            self.base.agent = self.original_agent
        return await self.base.__aexit__(exc_type, exc_value, traceback)
