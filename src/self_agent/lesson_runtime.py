"""Opt-in runnable decorator: scoped context before generation, bounded evidence checking after."""
import copy
import json
import time
from contextvars import ContextVar
from self_agent.models import sanitize, digest
from .lessons import POLICY, FALLBACK_RULE

CURRENT_LESSONS = ContextVar('self_agent_lessons', default=None)
SAFE_RESPONSE = 'Em chưa thể xác nhận chính xác thông tin này từ dữ liệu hiện có.'


def add_evidence(context, record):
    """Detached, redacted evidence scoped to one turn, never parsed from user prose."""
    record = sanitize(record, context.get('secrets', ()))
    records = context.setdefault('evidence', [])
    key = digest({k: v for k, v in record.items() if k != 'origin'})
    if key not in context.setdefault('evidence_keys', set()):
        context['evidence_keys'].add(key)
        records.append({**record, 'evidence_id': 'e' + str(len(records))})


class TurnEvidenceBridge:
    """Observe this harness instance's orchestration outputs before generation.

    No core/global patch, no tool re-execution. Restore original instance
    attributes on close; ContextVar prevents evidence crossing concurrent turns.
    """
    def __init__(self, base):
        self.base, self.originals = base, {}

    def install(self):
        for name in ('_prefetch_read_tools', '_execute_confirmed_mutation'):
            original = getattr(self.base, name, None)
            if not callable(original):
                continue
            self.originals[name] = (name in vars(self.base), original)

            async def observe(context, *args, _original=original, _name=name, **kwargs):
                result = await _original(context, *args, **kwargs)
                current = CURRENT_LESSONS.get()
                if current and current['lessons']:
                    current.setdefault('observed_stages', set()).add(_name)
                    identity = getattr(context, 'identity', None)
                    profile = getattr(identity, 'profile', None) or {}
                    current['secrets'] = [*current.get('secrets', ()), getattr(identity, 'phone', None),
                                          *[profile.get(k) for k in ('name', 'address', 'phone', 'email')]]
                    for call in result[0]:
                        add_evidence(current, {'kind': 'tool', 'origin': 'orchestration',
                            'name': call.get('name'), 'args': call.get('args', {}), 'result': call.get('result')})
                    retrieved = getattr(context, 'retrieved', None)
                    for source in getattr(retrieved, 'knowledge', []) or []:
                        add_evidence(current, {'kind': 'source', 'origin': 'retrieved_context', 'source': source})
                return result

            setattr(self.base, name, observe)
        return self

    def restore(self):
        for name, (was_local, original) in self.originals.items():
            if was_local:
                setattr(self.base, name, original)
            else:
                delattr(self.base, name)
        self.originals.clear()


def grounded_verdict(verdict, answer, evidence):
    """Reject malformed approvals and unverifiable evidence citations.

    Semantic entailment still belongs to the model, but a bare `valid: true`
    can no longer approve a material claim without naming its actual evidence.
    """
    if (verdict.get('valid') is not True or verdict.get('unsupported_claims') != []
            or type(verdict.get('uncertainty_only')) is not bool):
        return False
    claims = verdict.get('claims')
    if not isinstance(claims, list):
        return False
    known = {item['evidence_id'] for item in evidence}
    for claim in claims:
        if not isinstance(claim, dict):
            return False
        text, refs = claim.get('text'), claim.get('evidence_ids')
        if (not isinstance(text, str) or not text.strip() or text not in answer
                or not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) or ref not in known for ref in refs)):
            return False
    return bool(claims) if verdict['uncertainty_only'] is False else not claims


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
        # Older lessons may contain an invented process in fallback. The runtime
        # applies the same evidence-neutral fallback rule to every lesson.
        lessons = [{**lesson, 'fallback': FALLBACK_RULE} for lesson in context['lessons']]
        augmented = {**payload, 'messages': [
            {'role': 'system', 'content': POLICY + '\nVerified learning context:\n' + json.dumps(lessons, ensure_ascii=False)},
            *payload.get('messages', [])]}
        context['trace']['injected'] = True
        result = await self.agent.ainvoke(augmented, **kwargs)
        messages = result.get('messages', [])
        index = next((i for i in range(len(messages)-1, -1, -1)
                      if get_field(messages[i], 'type', get_field(messages[i], 'role')) in {'ai', 'assistant'}
                      and text_content(get_field(messages[i], 'content'))), None)
        if index is None:
            context['trace']['validation'] = 'no_final_response'
            return result
        response = text_content(get_field(messages[index], 'content'))
        def tool_identity(message):
            return digest({'id': get_field(message, 'id'), 'tool_call_id': get_field(message, 'tool_call_id'),
                           'name': get_field(message, 'name'), 'content': text_content(get_field(message, 'content'))})

        inherited_tools = {tool_identity(m)
                           for m in payload.get('messages', [])
                           if get_field(m, 'type', get_field(m, 'role')) == 'tool'}
        for message in messages[:index]:
            if get_field(message, 'type', get_field(message, 'role')) == 'tool':
                if tool_identity(message) in inherited_tools:
                    continue
                content = text_content(get_field(message, 'content'))
                try:
                    content = json.loads(content)
                except ValueError:
                    pass
                add_evidence(context, {'kind': 'tool', 'origin': 'agent_tool_message',
                    'name': get_field(message, 'name'), 'args': {}, 'result': content})
        evidence = context.get('evidence', [])
        before = dict(getattr(self.model, 'usage', {}))
        validation_started = time.perf_counter()
        async def check(answer):
            verdict = await self.model.json(
                'Validate this Vietnamese answer against the selected lessons and supplied turn evidence. '
                'Return {"valid":boolean,"uncertainty_only":boolean,"claims":[{"text":"exact answer span",'
                '"evidence_ids":["e0"]}],"unsupported_claims":["exact unsupported answer span"]}. '
                'List every material business claim under the lesson, including fallback claims, negative '
                'availability claims and alternative future commitments. Every supported claim must cite '
                'evidence that explicitly entails it, with matching scope/product/time and successful action '
                'status where relevant. Failed tools and unrelated search hits do not establish a claim. '
                'Neither the answer nor the lesson is evidence. Missing search results do not prove nonexistence. '
                'Uncertainty-only means no business claim or future commitment, only an admission that the '
                'information is unverified. Honest uncertainty may pass with empty claims; material claims '
                'without explicit evidence must appear in unsupported_claims and fail. Ignore irrelevant lessons.',
                {'lessons': lessons, 'question': sanitize(context['question']), 'answer': sanitize(answer), 'evidence': evidence})
            return verdict, grounded_verdict(verdict, sanitize(answer), evidence)
        validation = 'passed'
        try:
            verdict, valid = await check(response)
            context['trace']['initial_grounding_valid'] = valid
            if not valid:
                rewritten = await self.model.json(
                    'Repair only the lesson violations in this Vietnamese answer. Return {"response":"..."}. '
                    'Preserve verified facts, action outcomes and customer consent; invent no new fact or promise. '
                    'You cannot call tools, create orders, schedule anything, or change an executed action. '
                    + FALLBACK_RULE,
                    {'lessons': lessons, 'question': sanitize(context['question']), 'answer': sanitize(response),
                     'violations': verdict, 'evidence': evidence})
                candidate = rewritten.get('response')
                if isinstance(candidate, str) and candidate.strip() and (await check(candidate))[1]:
                    response, validation = candidate, 'repaired'
                else:
                    response, validation = SAFE_RESPONSE, 'safe_fallback'
        except Exception as exc:
            response, validation = SAFE_RESPONSE, 'validator_failed'
            context['trace']['validator_error'] = type(exc).__name__
        context['trace'].update(validation=validation,
            tool_evidence_count=sum(item['kind'] == 'tool' for item in evidence),
            source_evidence_count=sum(item['kind'] == 'source' for item in evidence),
            evidence_origins=sorted({item['origin'] for item in evidence}),
            evidence_stages=sorted(context.get('observed_stages', ())),
            fallback_policy='uncertainty_only',
            grounding_contract='evidence_citations_v1',
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
