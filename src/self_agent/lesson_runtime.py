"""Inject compact learning memory before generate; never rewrite the response."""
from contextvars import ContextVar
from .lessons import POLICY, compact_context, validate_lesson
from .guardrails import MEMORY_POLICY, VERSION, lesson_risks

CURRENT_LESSONS = ContextVar('self_agent_lessons', default=None)


class LessonAgent:
    def __init__(self, agent, model=None):
        self.agent = agent

    async def prepare(self):
        context = CURRENT_LESSONS.get()
        if context and context.get('prepare') and not context.get('prepared'):
            context['prepared'] = True
            await context['prepare'](context)

    def augment(self, payload):
        context=CURRENT_LESSONS.get()
        if not context or not context['lessons']:
            return payload
        cards=[]
        seen=set()
        blocked=[]
        for lesson in context['lessons']:
            if not validate_lesson(lesson):
                blocked.append({'id': lesson.get('id') if isinstance(lesson,dict) else None,
                                'findings':lesson_risks(lesson) or [{'codes':['invalid_lesson']}]})
                continue
            card=compact_context(lesson)
            if card not in seen and len(cards)<3:
                seen.add(card)
                cards.append(card)
        context['trace']['guardrails']={'version':VERSION,'blocked_lessons':blocked}
        if not cards:
            context['trace'].update(injected=False,injected_lesson_count=0,response_modified=False)
            return payload
        content=POLICY+' '+MEMORY_POLICY+'\nLearning memory:\n<learning_memory>\n'+'\n\n'.join(cards)+'\n</learning_memory>'
        context['trace'].update(injected=True,mode='memory_only',injected_chars=len(content),
                                injected_lesson_count=len(cards),response_modified=False)
        return {**payload,'messages':[{'role':'system','content':content},*payload.get('messages',[])]}

    async def ainvoke(self, payload, **kwargs):
        await self.prepare()
        return await self.agent.ainvoke(self.augment(payload),**kwargs)

    async def astream(self, payload, **kwargs):
        await self.prepare()
        async for part in self.agent.astream(self.augment(payload),**kwargs):
            yield part
