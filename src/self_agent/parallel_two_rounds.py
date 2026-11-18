"""Two frozen global rounds, isolated scenario processes and bounded parallelism."""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .scenario_runner import load_scenarios, DEFAULT_SCENARIOS
from .parallel_scenario_runner import run_parallel, utf8_process_env
from .evaluation.round_config import prepare_round
from .evaluation.compare_scenario_rounds import score


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


async def launch_prepared(scenario, directory, output, learning_root, *, prepared_round, round_number):
    sid = scenario['scenario_id']
    target = output / sid
    target.mkdir()
    command = [sys.executable, '-m', 'self_agent.scenario_runner', '--scenarios', str(directory.resolve()),
               '--scenario-id', sid, '--limit', '0', '--output', str(target.resolve()),
               '--learning-root', str((learning_root/sid).resolve()), '--runtime-root', str((target/'runtime').resolve()),
               '--round', str(round_number), '--prepared-round', str(prepared_round.resolve())]
    with (target/'console.log').open('wb') as log:
        process = await asyncio.create_subprocess_exec(*command, stdout=log, stderr=asyncio.subprocess.STDOUT,
                                                       env=utf8_process_env())
        try:
            return await process.wait()
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
                await process.wait()
            raise


def diagnostics(root):
    reports = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(root.glob('SC-*-call_*.json'))]
    reviews = [v for r in reports for v in (r.get('learning') or {}).get('issue_reviews', [])]
    patterns = {(c['value'].get('lesson') or {}).get('id',c['value']['id']):c['value'] for r in reports for c in r.get('artifact_changes', [])
                if c['path'].startswith('patterns/')}
    reasons = {}
    for review in reviews:
        for reason in review.get('rejection_reasons') or ([review['rejection']] if review.get('rejection') else []):
            reasons[reason] = reasons.get(reason,0) + 1
    return {'sessions':len(reports),
            'completed_learning_jobs':sum((r.get('job') or {}).get('status') == 'done' for r in reports),
            'detector_failures':sum(bool((r.get('learning') or {}).get('detector_error')) for r in reports),
            'detected_candidates':sum((r.get('learning') or {}).get('detection',{}).get('candidate_count',0) for r in reports),
            'turns_scanned':sum((r.get('learning') or {}).get('detection',{}).get('scan',{}).get('turns_scanned',0) for r in reports),
            'reviewed_issues':len(reviews),
            'verified_issues':sum(v.get('verified') is True for v in reviews),
            'verified_per_reviewed':sum(v.get('verified') is True for v in reviews)/len(reviews) if reviews else None,
            'inventory_verified_issues':sum(v.get('verified') is True and v.get('verification_basis') == 'evidence_inventory_audit' for v in reviews),
            'alignment_rejections':sum((r.get('learning') or {}).get('detection',{}).get('skipped_unmatched_question',0) for r in reports),
            'rejections':reasons,
            'approved_lessons':sum(p.get('status') == 'approved' and bool(p.get('lesson')) for p in patterns.values()),
            'pending_lessons':sum(p.get('status') == 'pending_lesson' for p in patterns.values()),
            'injected_turns':sum((t.get('lesson_trace') or {}).get('injected') is True for r in reports for t in r['turns'])}


async def run_rounds(scenarios, directory, output, *, instruction_root, settings, workers=2,
                     judge=False, allow_no_lessons=False, strict=False, launch=launch_prepared, evaluate=score):
    if workers not in (1,2):
        raise ValueError('workers must be 1 or 2')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    summary = {'status':'running', 'scenario_count':len(scenarios),
               'scenario_ids':[s['scenario_id'] for s in scenarios], 'workers':workers, 'rounds':{},
               'learning_applied':False,'warnings':[],
               'limitation':'Round 1 shares only frozen lessons from all round-0 scenarios. '
                            'Two rounds alone do not isolate sampling variance or prove unseen generalization.'}
    def save(): write_json(output/'summary.json',summary)
    save()
    try:
        for number in (0,1):
            root = output/f'round{number}'
            prepare_round(scenarios,root,instruction_root,output/'learning-memory', round_number=number,
                          settings=settings,baseline=output/'round0' if number else None,
                          skip_failed_baseline=not strict)
            manifest = json.loads((root/'round_manifest.json').read_text(encoding='utf-8'))
            if number and not manifest['lessons_loaded'] and strict and not allow_no_lessons:
                summary['status'] = 'stopped_no_approved_lessons'
                summary['next_step'] = 'Inspect round0 verifier rejections; no round1 inference or judge was run.'
                save()
                return summary
            if number and not manifest['lessons_loaded']:
                summary['warnings'].append('No approved lesson: round1 still runs, but no learning effect can be claimed.')
            async def launch_one(scenario, folder, targets, memory):
                return await launch(scenario,folder,targets,memory,prepared_round=root,round_number=number)
            records = await run_parallel(scenarios,directory,root/'workers',workers=workers,launch=launch_one)
            # Deterministic merge; runtime/logs and customer/learning memory remain isolated per SC.
            for scenario in scenarios:
                for path in sorted((root/'workers'/scenario['scenario_id']).glob('SC-*-call_*.json')):
                    write_json(root/path.name,json.loads(path.read_text(encoding='utf-8')))
            summary['rounds'][f'round{number}'] = {'scenarios':records,'diagnostics':diagnostics(root)}
            save()
            if any(record['status'] != 'done' for record in records):
                summary['warnings'].append(f'round{number} contains failed scenarios; continuing with exclusions in evaluation.')
                if not strict:
                    continue
                summary['status'] = f'round{number}_failed'
                save()
                return summary
        summary['learning_applied'] = summary['rounds']['round1']['diagnostics']['injected_turns'] > 0
        if judge:
            await evaluate(SimpleNamespace(round0=output/'round0',round1=output/'round1',
                                           scenarios=Path(directory),output=output/'comparison.json',allow_partial=not strict))
        summary['status'] = 'completed_with_failures' if any(r['status'] != 'done' for data in summary['rounds'].values() for r in data['scenarios']) else 'completed'
        summary['judge_completed'] = judge
        save()
        return summary
    except BaseException as exc:
        summary.update(status='interrupted' if isinstance(exc,asyncio.CancelledError) else 'failed',error=type(exc).__name__)
        save()
        raise
    finally:
        # Read saved artifacts only, including partial/no-judge runs.
        from .evaluation.review import write_review
        try:
            write_review(output/'round0', output/'round1', output/'review.html')
        except (OSError, ValueError, KeyError, TypeError) as review_error:
            summary['review_error'] = type(review_error).__name__
            save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenarios',type=Path,default=DEFAULT_SCENARIOS)
    parser.add_argument('--limit',type=int,default=60)
    parser.add_argument('--scenario-id',action='append',default=[])
    parser.add_argument('--workers',type=int,choices=(1,2),default=2)
    parser.add_argument('--output',type=Path,default=Path('outputs/self-agent/parallel-two-rounds')/datetime.now().strftime('%Y%m%d-%H%M%S'))
    parser.add_argument('--judge',action='store_true')
    parser.add_argument('--allow-no-lessons',action='store_true')
    parser.add_argument('--strict',action='store_true',help='Stop between rounds on a failed worker or no approved lessons')
    parser.add_argument('--list',action='store_true')
    args = parser.parse_args()
    if args.limit < 0: parser.error('--limit must be nonnegative')
    scenarios = load_scenarios(args.scenarios,args.scenario_id,limit=0 if args.scenario_id else args.limit)
    if not args.scenario_id and args.limit and len(scenarios) != args.limit:
        parser.error(f'Requested {args.limit} scenarios, found only {len(scenarios)}')
    sessions = sum(len(s['calls']) for s in scenarios)
    turns = sum(len(c.get('customer_turns_asr') or c.get('customer_turns') or []) for s in scenarios for c in s['calls'].values())
    print(f'{len(scenarios)} SC; {sessions} sessions / {turns} turns per round; workers={args.workers}')
    if args.list:
        print(', '.join(s['scenario_id'] for s in scenarios))
        return
    from dotenv import load_dotenv
    load_dotenv()
    if os.getenv('KNOWLEDGE_GAP_LOOP_ENABLED','').lower() != 'true':
        parser.error('Set KNOWLEDGE_GAP_LOOP_ENABLED=true')
    instruction_root = os.getenv('AGENT_INSTRUCTIONS_ROOT') or Path(__file__).resolve().parents[2]/'data/memory-root/agents/telesales_agent'
    settings = {k:os.getenv(k,'') for k in ('LLM_PROVIDER','LLM_MODEL','GROQ_MODEL','GEMINI_MODEL',
                'DEEPAGENT_THINKING_LEVEL','DEEPAGENT_CHECKPOINT_SCOPE','KNOWLEDGE_BACKEND','PINECONE_INDEX_NAME','PINECONE_NAMESPACE')}
    summary = asyncio.run(run_rounds(scenarios,args.scenarios,args.output,instruction_root=instruction_root,
        settings=settings,workers=args.workers,judge=args.judge,allow_no_lessons=args.allow_no_lessons,strict=args.strict))
    print(f"{summary['status']}: {args.output/'summary.json'}")
    if summary['status'] not in {'completed','completed_with_failures'}: raise SystemExit(1)


if __name__ == '__main__': main()
