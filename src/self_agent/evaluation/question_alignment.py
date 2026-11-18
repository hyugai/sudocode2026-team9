"""Bind frozen learning questions to recorded input without fuzzy matching.

The learner sees normalized/redacted state messages; the runner also records
the original customer input. Those strings can differ within the SAME turn.
Require identical actual input across rounds and recorded baseline provenance
before accepting an alias. Never strip accents, numbers or policy conditions.
"""


def align_case(case, before, after):
    call, turn_id = case['call'], case['turn_id']
    if type(turn_id) is not int or turn_id < 1:
        raise ValueError(f'Invalid frozen gap turn: {call}')
    turns = []
    for name, records in (('round0', before), ('round1', after)):
        report = records.get(call)
        if not report or turn_id > len(report.get('turns', [])):
            raise ValueError(f'Frozen gap turn missing: {call} turn {turn_id} in {name}')
        turns.append(report['turns'][turn_id - 1])
    question = turns[0].get('customer')
    if not isinstance(question, str) or not question.strip() or question != turns[1].get('customer'):
        raise ValueError(f'Frozen gap question changed between rounds: {call} turn {turn_id}')
    frozen = case.get('frozen_question', case['question'])
    source = 'exact_text'
    if frozen != question:
        if turns[0].get('learning_question') == frozen:
            source = 'round0.turns.learning_question'
        else:
            origin = (before[call].get('learning') or {}).get('evaluation_cases', [])
            matches = [row for row in origin if all(row.get(key) == value for key, value in (
                ('id', case.get('id')), ('gap_id', case.get('gap_id')),
                ('turn_id', turn_id), ('question', frozen))) and row.get('id')]
            if len(matches) != 1:
                raise ValueError(f'Frozen gap question has no recorded baseline alias: {call} turn {turn_id}')
            source = 'round0.learning.evaluation_cases'
    return {**case, 'question': question, 'frozen_question': frozen,
            'question_alignment': {'mode': 'exact' if source == 'exact_text' else 'recorded_alias',
                                   'source': source, 'actual_input_equal_across_rounds': True}}


def align_cases(cases, before, after):
    """Preflight EVERY case before spending tokens on the first verdict."""
    return [align_case(case, before, after) for case in cases]
