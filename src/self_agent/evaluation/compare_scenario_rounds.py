"""Compare frozen knowledge gaps only; no session-success or reflection judge."""
import argparse
import asyncio
import json
from pathlib import Path
from ..scenario_runner import load_scenarios
from ..models import digest
from ..lessons import load_lesson
from .knowledge_judge import score_gaps
from .question_alignment import align_cases


def learning_runtime(reports):
    traces = [turn.get('lesson_trace') for report in reports.values() for turn in report['turns']]
    known = [trace for trace in traces if trace is not None]
    return {'total_turns': len(traces),
            'routed_turns': sum(bool(t.get('selected_lessons')) for t in known),
            'injected_turns': sum(t.get('injected') is True for t in known),
            'routing_failures': sum(t.get('routing') == 'failed' for t in known),
            'validation_not_invoked': sum(bool(t.get('selected_lessons')) and t.get('validation') == 'not_invoked' for t in known),
            'injection_trace_available': all('injected' in t for t in known)}


def read_round(root):
    reports = {}
    for path in Path(root).glob('SC-*-call_*.json'):
        report = json.loads(path.read_text(encoding='utf-8'))
        reports[f"{report['scenario_id']}/{report['call']}"] = report
    return reports


def valid_report(report):
    return (report is not None and not report.get('error') and (report.get('job') or {}).get('status') == 'done'
            and not (report.get('learning') or {}).get('detector_error'))


def check_rounds(root0, root1, *, allow_partial=False):
    m0, m1 = [json.loads((Path(p) / 'round_manifest.json').read_text(encoding='utf-8')) for p in (root0, root1)]
    if (m0['round'] != 0 or m1['round'] != 1 or m0['signature'] != m1['signature']
            or m0['signature'].get('learning_scope') != 'knowledge_gap_and_reflection_v1'):
        raise ValueError('Run fresh knowledge-gap rounds with identical tests/configuration and clean RAM')
    before, after = read_round(root0), read_round(root1)
    if not allow_partial and (not before or before.keys() != after.keys()):
        raise ValueError('Both rounds must contain the same completed calls')
    if not allow_partial and any(not valid_report(r) for r in [*before.values(), *after.values()]):
        raise ValueError('Incomplete dialogue/learning: fix the run before comparing')
    expected = [dict(case, call=key) for key in sorted(before)
                if valid_report(before[key])
                for case in (before[key].get('learning') or {}).get('evaluation_cases', [])]
    if m1.get('gap_cases') != expected or m1.get('gap_cases_hash') != digest(expected):
        raise ValueError('Frozen gap cases differ from round 0')
    if allow_partial:
        exclusions=[]
        selected=set()
        ids=set(m1.get('scenario_hashes',{})) or {k.split('/')[0] for k in before.keys()|after.keys()}
        for sid in sorted(ids):
            calls=m1.get('scenario_calls',{}).get(sid) or sorted({k.split('/')[1] for k in before.keys()|after.keys() if k.startswith(sid+'/')})
            bad=[{'call':sid+'/'+call,'reason':'baseline_missing_or_failed' if not valid_report(before.get(sid+'/'+call)) else 'round1_missing_or_failed'}
                 for call in calls if not valid_report(before.get(sid+'/'+call)) or not valid_report(after.get(sid+'/'+call))]
            if bad: exclusions.append({'scenario_id':sid,'calls':bad})
            else: selected.add(sid)
        before={k:r for k,r in before.items() if k.split('/')[0] in selected}
        after={k:r for k,r in after.items() if k.split('/')[0] in selected}
        m1={**m1,'comparison_exclusions':exclusions}
    return before, after, m0, m1


async def score(args):
    before, after, m0, m1 = check_rounds(args.round0, args.round1,allow_partial=getattr(args,'allow_partial',False))
    ids = sorted(m0.get('scenario_hashes',{})) or sorted({r['scenario_id'] for r in before.values()})
    scenarios = load_scenarios(args.scenarios, ids, 0)
    if digest(scenarios) != m0['signature']['tests']:
        raise ValueError('Scenario files changed after round 0')
    for entry in m1.get('lesson_files', []):
        lesson = load_lesson(Path(args.round1) / 'lessons/approved' / (entry['id'] + '.md'))
        if digest(lesson) != entry['hash']:
            raise ValueError('Frozen lesson changed after round 1')
    cases = [c for c in m1['gap_cases'] if c['call'] in before]
    aligned = align_cases(cases, before, after)
    if getattr(args, 'preflight', False):
        result = {'status':'preflight_passed','frozen_case_count':len(aligned),
                  'recorded_question_aliases':sum(c['question_alignment']['mode']=='recorded_alias' for c in aligned),
                  'compared_scenarios':len({r['scenario_id'] for r in before.values()}),
                  'model_requests':0}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    from dotenv import load_dotenv
    from ..adapters.llm import LearningModel
    load_dotenv()
    judge = LearningModel()
    targeted = await score_gaps(judge, cases, before, after)
    runtime = learning_runtime(read_round(args.round1))
    summary = {'method': 'Frozen question-level knowledge-gap evaluation with checked source references',
               'scope': 'knowledge_gap_v1', 'knowledge_gap_quality': targeted,
               'evaluation_population':'successful_pairs_subset' if m1.get('comparison_exclusions') else m1.get('evaluation_population','full_selected_dataset'),
               'excluded_scenarios':m1.get('comparison_exclusions',[]),
               'compared_scenarios':sorted({r['scenario_id'] for r in before.values()}),
               'source_baseline':m1.get('source_baseline'),
               'learning_scope': m1['signature']['learning_scope'],
               'reflection': {'approved_lessons_loaded': sum(v == 'reflection' for v in m1.get('lesson_mechanisms',{}).values()),
                              'quality_evaluated': False,
                              'note': 'Reflection lessons may affect responses, but are not scored as knowledge-gap resolutions.'},
               'lessons_loaded': m1['lessons_loaded'], 'learning_applied': runtime['injected_turns'] > 0,
               'learning_runtime': runtime, 'lesson_sources': m1.get('lesson_sources', []),
               'detector_failures': [sum(bool((r.get('learning') or {}).get('detector_error')) for r in records.values())
                                     for records in (before, after)], 'evaluation_usage': judge.usage,
               'review_report_hashes': {'round0':{k:digest(v) for k,v in read_round(args.round0).items()},
                                        'round1':{k:digest(v) for k,v in read_round(args.round1).items()}}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    from .review import write_review
    write_review(args.round0, args.round1, args.output.parent/'review.html', comparison=summary)
    print(json.dumps({k: v for k, v in targeted.items() if k not in {'details','manual_review_case_ids'}}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round0', required=True, type=Path)
    parser.add_argument('--round1', required=True, type=Path)
    parser.add_argument('--scenarios', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--allow-partial',action='store_true')
    parser.add_argument('--preflight',action='store_true',help='Check all question alignments offline, without LLM/DB calls')
    asyncio.run(score(parser.parse_args()))
