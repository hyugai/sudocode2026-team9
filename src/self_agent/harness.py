"""Composition facade. The existing harness and benchmark never import this."""
import asyncio
import traceback
from .config import LearningConfig
from .models import LearningJob, digest, snapshot


class SelfAgentHarness:
    def __init__(self, base, *, config=None, learner_factory=None, lessons=(), validation_model=None):
        self.base = base
        self.config = config if config is not None else LearningConfig.from_env()
        self.learner_factory = learner_factory
        self.memory = self.learner = self.worker = None
        self.lock = asyncio.Lock()
        from .lessons import LessonRouter
        self.lesson_router = LessonRouter(lessons if self.config.enabled else ())
        self.validation_model = validation_model
        self.lesson_traces = {}

    async def __aenter__(self):
        import os
        if self.lesson_router.lessons and os.getenv('DEEPAGENT_CHECKPOINT_SCOPE', 'turn') == 'conversation':
            raise ValueError('Scoped lesson routing requires per-turn checkpoints, not conversation checkpoints')
        await self.base.__aenter__()
        if self.lesson_router.lessons:
            from .lesson_runtime import LessonAgent
            from .adapters.llm import LearningModel
            self.base.agent = LessonAgent(self.base.agent, self.validation_model or LearningModel())
        return self

    async def run_turn(self, turn_input, state=None, *, on_text=None, on_status=None):
        lessons = self.lesson_router.select(getattr(turn_input, 'text', '') or '')
        if not lessons:
            return await self.base.run_turn(turn_input, state, on_text=on_text, on_status=on_status)
        from .lesson_runtime import CURRENT_LESSONS
        from .models import digest
        trace = {'selected_lessons': [{'id': l['id'], 'hash': digest(l)} for l in lessons], 'validation': 'not_invoked'}
        token = CURRENT_LESSONS.set({'lessons': lessons, 'question': turn_input.text, 'trace': trace})
        try:
            result = await self.base.run_turn(turn_input, state, on_text=on_text, on_status=on_status)
            self.lesson_traces.setdefault(result.conversation_id, []).append(trace)
            if on_text:
                await on_text(result.response_text or '')
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
        return await self.base.__aexit__(exc_type, exc_value, traceback)
