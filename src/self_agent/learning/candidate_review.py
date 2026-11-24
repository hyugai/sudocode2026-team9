"""Turn-scoped discovery and evidence inventory checks; no business writes."""
KNOWLEDGE_REASONS = {'missing_knowledge','retrieval_failure','unsupported_claim'}
REFLECTION_REASONS = {'reasoning_failure','tool_failure','context_mismatch'}
GAP_CRITERION = ('Answer the customer knowledge question completely using explicit, applicable source evidence. '
                 'If the evidence is insufficient, acknowledge the remaining uncertainty without inventing '
                 'facts, negative availability claims, alternative procedures or future commitments.')


class DetectorSchemaError(ValueError):
    def __init__(self, result):
        super().__init__('Detector must return an object with a gaps array of objects')
        self.learning_diagnostics={'stage':'detector_schema','error':type(self).__name__,
            'has_gaps':isinstance(result,dict) and 'gaps' in result,
            'gaps_type':type(result.get('gaps')).__name__ if isinstance(result,dict) else 'not_an_object'}


def aligned_turns(snapshot):
    evidence = {e['turn_id']:e for e in snapshot.get('turn_evidence', [])}
    turns = []
    for index, message in enumerate(snapshot['messages']):
        if message['role'] not in {'user','customer'}:
            continue
        turn_id = len(turns) + 1
        turns.append({'message_id':message.get('message_id',index), 'turn_id':turn_id,
                      'question':message['content'], 'evidence':evidence.get(turn_id)})
    return turns


def prior_evidence(snapshot, turn_id):
    # Earlier tool/source facts can support later answers; earlier assistant
    # prose cannot. Never include evidence from a future turn.
    return [{**{k:v for k,v in e.items() if k != 'agent_response'},
             'sources':e.get('sources',[]),'promotions':e.get('promotions',[]),'tool_calls':e.get('tool_calls',[])}
            for e in snapshot.get('turn_evidence', []) if e['turn_id'] < turn_id]


def evidence_inventory(payload):
    paths = []
    for prefix, record in [('evidence',payload['evidence']),
                           *[(f'prior_evidence.{i}',e) for i,e in enumerate(payload.get('prior_evidence',[]))]]:
        for group in ('tool_calls','sources','promotions'):
            rows = record.get(group, [])
            if group == 'tool_calls' and rows:
                paths.extend(f'{prefix}.tool_calls.{i}.result' for i in range(len(rows)))
            else:
                # Empty lists matter: the audit can show that the supplied
                # evidence contains no source, without pretending a fact is false.
                paths.append(f'{prefix}.{group}')
    return paths


async def discover(model, snapshot):
    turns = aligned_turns(snapshot)
    scoped = [t for t in turns if t['evidence'] is not None]
    requests = scoped or [None]  # transcript-only compatibility remains explicit
    candidates, errors, dropped, schema_retries = [], [], 0, 0
    request=getattr(model,'candidates',model.json)
    for turn in requests:
        payload = snapshot if turn is None else {
            'current_turn':turn, 'prior_evidence':prior_evidence(snapshot,turn['turn_id']),
            'messages':snapshot['messages'][:next(i+1 for i,m in enumerate(snapshot['messages'])
                if m.get('message_id',i) == turn['message_id'])],
            'open_questions':snapshot.get('open_questions',[])}
        try:
            result = await request(
                'Find unanswered business questions AND atomic unsupported business claims in this turn. '
                'For high recall, extract every material business claim requiring source confirmation, '
                'even if it appears plausible or correct. unsupported_claim is a tentative audit candidate, '
                'not a verdict: a separate verifier must reject supported claims. '
                'Inspect each answer clause separately: amounts, eligibility, scope, time validity, '
                'conditions, availability, commitments and the evidence needed for each. Do not stop '
                'after the first issue. Include honest unanswered questions as missing_knowledge. '
                'Also detect demonstrated context/reasoning/action failures as reflection, not knowledge. '
                'If evidence marks the answer interrupted or output_complete=false, audit only explicit claims in the available output; '
                'do not infer a failure or a completed commitment from the missing continuation. '
                'Return {"gaps":[{"reason":"missing_knowledge|retrieval_failure|unsupported_claim|'
                'reasoning_failure|tool_failure|context_mismatch","claim":"exact atomic answer span or null",'
                '"required_fact":"what needs verification"}]}. For transcript-only input include real '
                'message_id and turn_id. For current_turn input IDs are assigned by the application; '
                'do not infer them. Multiple claims in one answer may produce multiple candidates. '
                'Do not invent errors or classify customer consent as business policy. '
                'Use prior evidence only when still applicable; an earlier assistant assertion is not '
                'authority. Missing evidence is not proof of falsehood. Return [] inside gaps if no issue.',payload)
            rows = result.get('gaps') if isinstance(result,dict) else None
            if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
                schema_retries += 1
                result = await request(
                    'Correct only the candidate detector JSON schema for this turn. Return exactly '
                    '{"gaps":[{"reason":"missing_knowledge|retrieval_failure|unsupported_claim|'
                    'reasoning_failure|tool_failure|context_mismatch","claim":"exact answer span or null",'
                    '"required_fact":"what needs verification"}]}. If there is no issue return '
                    '{"gaps":[]}, never null, an object inside gaps, prose or a bare array. '
                    'Do not invent issues to fill the array. Preserve real candidate facts and use the supplied turn.',
                    {'input':payload,'previous_output':result})
                rows=result.get('gaps') if isinstance(result,dict) else None
                if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
                    raise DetectorSchemaError(result)
            dropped += max(0,len(rows)-16) if turn else 0
            for row in rows[:16] if turn else rows:
                if turn:
                    row = {**row,'message_id':turn['message_id'],'turn_id':turn['turn_id'],
                           'origin':'turn_detector'}
                candidates.append(row)
        except Exception as exc:
            errors.append({'turn_id':turn['turn_id'] if turn else None,'error':type(exc).__name__,
                           'diagnostics':getattr(exc,'learning_diagnostics',{'stage':'detector_request'})})
    return candidates, {'turns_available':len(turns),'turns_scanned':len(scoped),
                        'requests':len(requests),'errors':errors,'schema_retries':schema_retries,'skipped_over_limit':dropped}


def path_allowed(path, mechanism):
    if not isinstance(path,str): return False
    parts = path.split('.')
    if mechanism == 'reflection' and parts[0] == 'conversation':
        return len(parts) == 3 and parts[2] == 'content'
    if parts[0] == 'prior_evidence':
        if len(parts) < 3 or not parts[1].isdigit(): return False
        parts = ['evidence',*parts[2:]]
    if parts[0] != 'evidence' or len(parts) < 2: return False
    if parts[1] in {'sources','promotions'}: return True
    return len(parts) >= 4 and parts[1] == 'tool_calls' and parts[2].isdigit() and parts[3] == 'result'


def inventory_audit_valid(checked, payload, mechanism):
    audit = checked.get('audit')
    if (mechanism != 'knowledge_gap' or checked.get('assessment') != 'unsupported_by_evidence'
            or not isinstance(audit,dict) or audit.get('support_status') != 'not_established'
            or audit.get('coverage') != 'complete'):
        return False
    paths = audit.get('checked_paths')
    return (isinstance(paths,list) and all(isinstance(p,str) for p in paths)
            and set(paths) == set(evidence_inventory(payload)))
