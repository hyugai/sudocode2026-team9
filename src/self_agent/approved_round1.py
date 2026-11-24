"""Reuse complete approved baseline scenarios for a clearly labeled round-1 subset."""
import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .models import digest
from .scenario_runner import DEFAULT_SCENARIOS, load_scenarios
from .parallel_two_rounds import write_json, diagnostics, launch_prepared
from .parallel_scenario_runner import run_parallel
from .evaluation.round_config import prepare_round, approved_lesson
from .evaluation.compare_scenario_rounds import score


def select_baseline(baseline, directory):
    baseline=Path(baseline).resolve()
    root=baseline if (baseline/'round_manifest.json').exists() else baseline/'round0'
    manifest=json.loads((root/'round_manifest.json').read_text(encoding='utf-8'))
    if manifest['round'] != 0: raise ValueError('Source must be a round-0 baseline')
    ids=list(manifest.get('scenario_hashes',{}))
    if not ids: raise ValueError('Source baseline has no frozen scenario hashes')
    scenarios=load_scenarios(directory,ids,0)
    if (digest(scenarios) != manifest['signature']['tests'] or any(
            manifest['scenario_hashes'].get(s['scenario_id']) != digest(s) for s in scenarios)):
        raise ValueError('Dataset changed since source round 0')
    chosen, excluded, reports, lesson_ids = [], [], {}, set()
    for scenario in scenarios:
        sid=scenario['scenario_id']
        found={}
        for call in scenario['calls']:
            path=root/f'{sid}-{call}.json'
            if not path.exists(): path=root/'workers'/sid/f'{sid}-{call}.json'
            if path.exists():
                report=json.loads(path.read_text(encoding='utf-8'))
                if report.get('scenario_id') != sid or report.get('call') != call:
                    raise ValueError('Source report identity mismatch')
                found[call]=report
        if (set(found) != set(scenario['calls']) or any(r.get('error') or (r.get('job') or {}).get('status') != 'done'
                or (r.get('learning') or {}).get('detector_error') for r in found.values())):
            excluded.append({'scenario_id':sid,'reason':'baseline_incomplete_or_failed'})
            continue
        approved=[lesson for r in found.values() for change in r.get('artifact_changes',[])
                  if (lesson:=approved_lesson(change,r['job']['job_id']))]
        if not approved:
            excluded.append({'scenario_id':sid,'reason':'no_valid_approved_lesson'})
            continue
        chosen.append(scenario)
        reports[sid]=found
        lesson_ids.update(lesson['id'] for lesson in approved)
    return {'root':root,'manifest':manifest,'scenarios':chosen,'reports':reports,
            'excluded':excluded,'approved_lesson_count':len(lesson_ids)}


def prepare_subset(plan, output, *, instruction_root, settings):
    """Validate before mutation; create a new subset, never change the source run."""
    original=plan['manifest']['signature']
    base={name:(Path(instruction_root)/name).read_text(encoding='utf-8') for name in ('agent.md','soul.md','tools.md')}
    if original['settings'] != settings or original['base_instructions'] != digest(base):
        raise ValueError('Model/retrieval settings or original instructions differ from source baseline')
    if not plan['scenarios']: raise ValueError('No complete scenarios with valid approved lessons')
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    metadata={'evaluation_population':'approved_completed_subset','source_baseline':str(plan['root']),
              'source_signature':original,'excluded_scenarios':plan['excluded'],
              'selection_warning':'Selected for having approved lessons; not an overall or unbiased improvement estimate.'}
    round0=output/'round0'
    prepare_round(plan['scenarios'],round0,instruction_root,output/'unused',round_number=0,settings=settings)
    for sid,calls in plan['reports'].items():
        for call,report in calls.items(): write_json(round0/f'{sid}-{call}.json',report)
    round1=output/'round1'
    prepare_round(plan['scenarios'],round1,instruction_root,output/'unused',round_number=1,settings=settings,baseline=round0)
    for root in (round0,round1):
        path=root/'round_manifest.json'
        manifest=json.loads(path.read_text(encoding='utf-8'))
        write_json(path,{**manifest,**metadata})
    write_json(output/'selection.json',{**metadata,'selected_scenarios':[s['scenario_id'] for s in plan['scenarios']],
                                      'approved_lesson_count':plan['approved_lesson_count'],
                                      'baseline_reports_hash':digest(plan['reports'])})
    return output


async def run_subset(plan, directory, output, *, workers=2, judge=False, launch=launch_prepared, evaluate=score):
    output=Path(output)
    root=output/'round1'
    summary={'status':'running','evaluation_population':'approved_completed_subset','source_baseline':str(plan['root']),
             'selected_scenarios':[s['scenario_id'] for s in plan['scenarios']], 'excluded_scenarios':plan['excluded'],
             'approved_lesson_count':plan['approved_lesson_count'],'learning_applied':False}
    write_json(output/'summary.json',summary)
    try:
        async def one(scenario,folder,targets,memory):
            return await launch(scenario,folder,targets,memory,prepared_round=root,round_number=1)
        records=await run_parallel(plan['scenarios'],directory,root/'workers',workers=workers,launch=one)
        for scenario in plan['scenarios']:
            for path in sorted((root/'workers'/scenario['scenario_id']).glob('SC-*-call_*.json')):
                write_json(root/path.name,json.loads(path.read_text(encoding='utf-8')))
        summary.update(scenarios=records,diagnostics=diagnostics(root))
        summary['learning_applied']=summary['diagnostics']['injected_turns'] > 0
        failed=any(r['status'] != 'done' for r in records)
        if judge:
            await evaluate(SimpleNamespace(round0=output/'round0',round1=root,scenarios=Path(directory),
                                           output=output/'comparison.json',allow_partial=True))
        summary.update(status='completed_with_failures' if failed else 'completed',judge_completed=judge,
                       warning='Failed scenarios are excluded from paired evaluation.' if failed else None)
    except BaseException as exc:
        summary.update(status='interrupted' if isinstance(exc,asyncio.CancelledError) else 'failed',error=type(exc).__name__)
        raise
    finally:
        write_json(output/'summary.json',summary)
        from .evaluation.review import write_review
        try:
            write_review(output/'round0', root, output/'review.html')
        except (OSError, ValueError, KeyError, TypeError) as review_error:
            summary['review_error'] = type(review_error).__name__
            write_json(output/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--scenarios',type=Path,default=DEFAULT_SCENARIOS)
    parser.add_argument('--workers',type=int,choices=(1,2),default=2)
    parser.add_argument('--output',type=Path,default=Path('outputs/self-agent/approved-round1')/datetime.now().strftime('%Y%m%d-%H%M%S'))
    parser.add_argument('--judge',action='store_true')
    parser.add_argument('--list',action='store_true')
    parser.add_argument('--prepare-only',action='store_true',help='Validate and freeze subset offline, without LLM/DB')
    args=parser.parse_args()
    plan=select_baseline(args.baseline,args.scenarios)
    print(f"Selected {len(plan['scenarios'])} SC, {plan['approved_lesson_count']} approved lessons: " + ', '.join(s['scenario_id'] for s in plan['scenarios']))
    print('Excluded: ' + ', '.join(e['scenario_id']+':'+e['reason'] for e in plan['excluded']))
    if args.list: return
    from dotenv import load_dotenv
    load_dotenv()
    instruction_root=os.getenv('AGENT_INSTRUCTIONS_ROOT') or Path(__file__).resolve().parents[2]/'data/memory-root/agents/telesales_agent'
    settings={k:os.getenv(k,'') for k in ('LLM_PROVIDER','LLM_MODEL','GROQ_MODEL','GEMINI_MODEL',
              'DEEPAGENT_THINKING_LEVEL','DEEPAGENT_CHECKPOINT_SCOPE','KNOWLEDGE_BACKEND','PINECONE_INDEX_NAME','PINECONE_NAMESPACE')}
    if not args.prepare_only and os.getenv('KNOWLEDGE_GAP_LOOP_ENABLED','').lower() != 'true':
        parser.error('Set KNOWLEDGE_GAP_LOOP_ENABLED=true')
    output=prepare_subset(plan,args.output,instruction_root=instruction_root,settings=settings)
    if args.prepare_only:
        print(f'Prepared offline: {output}')
        return
    result=asyncio.run(run_subset(plan,args.scenarios,output,workers=args.workers,judge=args.judge))
    print(f"{result['status']}: {output/'summary.json'}")
    if result['status'] not in {'completed','completed_with_failures'}: raise SystemExit(1)


if __name__ == '__main__': main()
