"""Opt-in runnable decorator: scoped context before generation, bounded evidence checking after."""
import copy
import json
import time
from contextvars import ContextVar
from self_agent.models import sanitize
from .lessons import POLICY

CURRENT_LESSONS = ContextVar('self_agent_lessons', default=None)


def get_field(message, key, default=None):
    return message.get(key, default) if isinstance(message, dict) else getattr(message, key, default)


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(b if isinstance(b, str) else b.get('text', '') for b in value if isinstance(b, (str, dict)))
    return ''


class LessonAgent:
    def __init__(self, agent, model):
        self.agent, self.model = agent, model

    async def ainvoke(self, payload, **kwargs):
        context = CURRENT_LESSONS.get()
        if not context or not context['lessons']:
            return await self.agent.ainvoke(payload, **kwargs)
        lessons = context['lessons']
        augmented = {**payload, 'messages': [
            {'role': 'system', 'content': POLICY + '\nVerified learning context:\n' + json.dumps(lessons, ensure_ascii=False)},
            *payload.get('messages', [])]}
        result = await self.agent.ainvoke(augmented, **kwargs)
        messages = result.get('messages', [])
        index = next((i for i in range(len(messages)-1, -1, -1)
                      if get_field(messages[i], 'type', get_field(messages[i], 'role')) in {'ai', 'assistant'}
                      and text_content(get_field(messages[i], 'content'))), None)
        if index is None:
            context['trace']['validation'] = 'no_final_response'
            return result
        response = text_content(get_field(messages[index], 'content'))
        evidence = []
        for message in messages:
            if get_field(message, 'type', get_field(message, 'role')) == 'tool':
                content = text_content(get_field(message, 'content'))
                try:
                    content = json.loads(content)
                except ValueError:
                    pass
                evidence.append({'tool': get_field(message, 'name'), 'result': sanitize(content)})
        before = dict(getattr(self.model, 'usage', {}))
        validation_started = time.perf_counter()
        async def check(answer):
            return await self.model.json(
                'Validate this Vietnamese answer against only the selected lessons and actual tool evidence. '
                'Return {"valid":boolean}. False for promises/facts lacking the evidence required by a lesson. '
                'Do not require irrelevant lessons or equate missing information with a false fact.',
                {'lessons': lessons, 'question': sanitize(context['question']), 'answer': sanitize(answer), 'evidence': evidence})
        validation = 'passed'
        try:
            verdict = await check(response)
            if verdict.get('valid') is not True:
                rewritten = await self.model.json(
                    'Repair only the lesson violations in this Vietnamese answer. Return {"response":"..."}. '
                    'Preserve verified facts, action outcomes and customer consent; invent no new fact or promise. '
                    'You cannot call tools, create orders, schedule anything, or change an executed action.',
                    {'lessons': lessons, 'question': sanitize(context['question']), 'answer': sanitize(response), 'evidence': evidence})
                candidate = rewritten.get('response')
                if isinstance(candidate, str) and candidate.strip() and (await check(candidate)).get('valid') is True:
                    response, validation = candidate, 'repaired'
                else:
                    response, validation = 'Em chưa thể xác nhận chính xác thông tin này từ dữ liệu hiện có.', 'safe_fallback'
        except Exception as exc:
            response, validation = 'Em chưa thể xác nhận chính xác thông tin này từ dữ liệu hiện có.', 'validator_failed'
            context['trace']['validator_error'] = type(exc).__name__
        context['trace'].update(validation=validation, tool_evidence_count=len(evidence),
            validation_ms=round((time.perf_counter()-validation_started)*1000, 3),
            validation_usage={k: v-before.get(k, 0) for k,v in getattr(self.model, 'usage', {}).items()})
        if response != text_content(get_field(messages[index], 'content')):
            updated = copy.copy(messages[index])
            if isinstance(updated, dict):
                updated = {**updated, 'content': response}
            else:
                updated.content = response
            result = {**result, 'messages': [*messages[:index], updated, *messages[index+1:]]}
        return result

    async def astream(self, payload, **kwargs):
        context = CURRENT_LESSONS.get()
        if not context or not context['lessons']:
            async for part in self.agent.astream(payload, **kwargs):
                yield part
            return
        # Do not stream an unchecked draft. Base turn consumes the final values event.
        kwargs.pop('stream_mode', None)
        result = await self.ainvoke(payload, **kwargs)
        yield ('values', result)
