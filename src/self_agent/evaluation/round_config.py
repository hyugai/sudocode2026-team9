"""Frozen, opt-in instruction overlay for M1 round comparisons; base files stay untouched."""
import json
from pathlib import Path
from self_agent.models import digest
from self_agent.lessons import POLICY, validate_lesson, markdown, load_lesson

PATTERNS = {
    "reasoning_failure": "Check the answer against evidence and preserve all applicable conditions.",
    "tool_failure": "Confirm an action only after its tool reports success.",
    "unsupported_claim": "Do not state an unverified claim as a fact.",
    "context_mismatch": "Check the current product and customer intent before reusing remembered information."}


def prepare_round(scenarios, output, instruction_root, pattern_root, *, round_number, settings, baseline=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'round_manifest.json').exists():
        raise ValueError('Round output already contains a manifest; choose a new directory')
    files = {name: (Path(instruction_root) / name).read_text(encoding='utf-8')
             for name in ('soul.md', 'agent.md', 'tools.md')}
    signature = {'tests': digest(scenarios), 'base_instructions': digest(files), 'settings': settings,
                 'customer_memory': 'empty_ram_shared_between_calls_only'}
    if baseline:
        old = json.loads((Path(baseline) / 'round_manifest.json').read_text(encoding='utf-8'))
        if old['round'] != 0 or old['signature'] != signature:
            raise ValueError('Round 1 must use the same tests, base instructions, model and retrieval settings as round 0')
    selected = {}
    lesson_sources = []
    frozen_lessons = []
    if round_number == 1:
        if not baseline:
            raise ValueError('Round 1 requires --baseline with a new clean round 0')
        # Frozen output of THIS round 0 is the sole source of lessons.
        # Never scan global pattern memory (it contains previous experiments).
        for path in sorted(Path(baseline).glob('SC-*-call_*.json')):
            report = json.loads(path.read_text(encoding='utf-8'))
            if report.get('job', {}).get('status') != 'done' or report.get('learning', {}).get('detector_error'):
                raise ValueError('Round 0 learning is incomplete; do not claim improvement')
            job_id = report['job']['job_id']
            for change in report.get('artifact_changes', []):
                item = change.get('value', {})
                reason = item.get('reason')
                lesson = item.get('lesson')
                if (change.get('path', '').startswith('patterns/') and change.get('change') in {'created', 'updated'}
                        and item.get('status') == 'approved' and item.get('scope') == 'general'
                        and item.get('pattern') == PATTERNS.get(reason)
                        and validate_lesson(lesson) and lesson.get('status') == 'approved'
                        and lesson.get('scope') == 'general' and item.get('lesson_hash') == digest(lesson)
                        and any(ref.get('job_id') == job_id for ref in item.get('evidence_refs', []))):
                    selected[reason] = PATTERNS[reason]
                    if not any(l['id'] == lesson['id'] for l in frozen_lessons):
                        frozen_lessons.append(lesson)
                    lesson_sources.append({'pattern_id': item['id'], 'job_id': job_id,
                                           'scenario_id': report['scenario_id'], 'call': report['call']})
    target = output / 'instructions'
    target.mkdir()
    if selected:
        files['agent.md'] += '\n\n# Verified learning context policy\n' + POLICY + '\n'
    lesson_dir = output / 'lessons/approved'
    for lesson in frozen_lessons:
        lesson_dir.mkdir(parents=True, exist_ok=True)
        path = lesson_dir / (lesson['id'] + '.md')
        path.write_text(markdown(lesson), encoding='utf-8')
        load_lesson(path)
    for name, content in files.items():
        (target / name).write_text(content, encoding='utf-8')
    manifest = {'round': round_number, 'signature': signature, 'applied_patterns': selected,
                'learning_applied': bool(selected), 'lesson_sources': lesson_sources,
                'lesson_files': [{'id': l['id'], 'hash': digest(l), 'path': str(lesson_dir / (l['id'] + '.md'))} for l in frozen_lessons],
                'instruction_hash': digest(files), 'limitations': 'External DB/catalog/policy must be kept equivalent by operator.'}
    (output / 'round_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return target.resolve()
