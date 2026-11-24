"""Composition facade. The existing harness and benchmark never import this."""
import time
from .config import LearningConfig
from .models import digest, sanitize
from .service import SelfLearningService


class SelfAgentHarness:
    def __init__(self, base, *, config=None, learner_factory=None, lessons=None, validation_model=None, routing_model=None):
        self.base = base
        self.config = config if config is not None else LearningConfig.from_env()
        self.learner_factory = learner_factory
        async def search(question):
            from telesale_agent.application.deepagent.tools.protocol import decode_tool_result
            return decode_tool_result(await self.base.mcp_tools["search_policy"].ainvoke({"query": question}))
        self.learning = SelfLearningService(config=self.config, learner_factory=learner_factory, search=search)
        from .lessons import LessonRouter, load_bank
        self.auto_memory=lessons is None and self.config.enabled
        self.lesson_router = LessonRouter((load_bank(self.config.root) if self.auto_memory else lessons or ()) if self.config.enabled else ())
        self.validation_model = routing_model or validation_model
        self.lesson_traces = {}
        self.started_sessions=set()
        self.session_routers = {}
        self.wrapper_installed=False
        self.original_agent = None

    @property
    def memory(self):
        return self.learning.memory

    @property
    def learner(self):
        return self.learning.learner

    @property
    def worker(self):
        return self.learning.worker

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
            self.session_routers[turn_input.conversation_id] = LessonRouter(load_bank(self.config.root))
            self.started_sessions.add(turn_input.conversation_id)
        router = self.session_routers.get(getattr(turn_input, "conversation_id", None), self.lesson_router)
        if not router.lessons:
            return await self.base.run_turn(turn_input, state, on_text=on_text, on_status=on_status)
        from .lesson_runtime import CURRENT_LESSONS
        from .models import digest
        if self.validation_model is None:
            from .adapters.llm import LearningModel
            self.validation_model = LearningModel()
        trace = {'lessons_loaded': len(router.lessons), 'selected_lessons': [],
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
            lessons = await router.select(sanitize(turn_input.text or '', secrets),
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
        return await self.learning.end_session(state, turn_results=turn_results, feedback=feedback)

    async def wait_learning(self, job_id):
        return await self.learning.wait_learning(job_id)

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.learning.close()
        if self.wrapper_installed:
            self.base.agent = self.original_agent
        return await self.base.__aexit__(exc_type, exc_value, traceback)
