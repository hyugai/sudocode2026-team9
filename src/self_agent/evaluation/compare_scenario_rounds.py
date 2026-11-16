"""Score two fixed scenario rounds separately from learning and the old benchmark."""
import argparse
import asyncio
import json
from pathlib import Path
from .run_gap_loop import compare
from ..scenario_runner import load_scenarios
from ..models import digest, sanitize


def read_round(root):
    reports = {}
    for path in Path(root).glob('SC-*-call_*.json'):
        report = json.loads(path.read_text(encoding='utf-8'))
        reports[f"{report['scenario_id']}/{report['call']}"] = report
    return reports


def check_rounds(root0, root1):
    m0, m1 = [json.loads((Path(p) / 'round_manifest.json').read_text(encoding='utf-8')) for p in (root0, root1)]
    if m0['round'] != 0 or m1['round'] != 1 or m0['signature'] != m1['signature']:
        raise ValueError('Rounds must use identical tests/configuration and clean RAM policy')
    before, after = read_round(root0), read_round(root1)
    if not before or before.keys() != after.keys():
        raise ValueError('Both rounds must contain the same completed calls')
    if any(r.get('error') for r in [*before.values(), *after.values()]):
        raise ValueError('Incomplete dialogue: fix the run before comparing quality')
    return before, after, m0, m1


async def score(args):
    before, after, m0, m1 = check_rounds(args.round0, args.round1)
    ids = sorted({r['scenario_id'] for r in before.values()})
    scenarios = load_scenarios(args.scenarios, ids, 0)
    if digest(scenarios) != m0['signature']['tests']:
        raise ValueError('Scenario files changed after round 0')
    from dotenv import load_dotenv
    load_dotenv()
    from ..adapters.llm import LearningModel
    judge = LearningModel()
    specs = {f"{s['scenario_id']}/{key}": value for s in scenarios for key, value in s['calls'].items()}
    verdicts = [{}, {}]
    details = []
    for key in sorted(before):
        pair = []
        for i, report in enumerate((before[key], after[key])):
            verdict = await judge.json(
                'You are an evaluator, not the learner. Judge this call against the supplied fixed specification. '
                'Check task outcome, product/context, price, consent, policy evidence, and whether actions really succeeded. '
                'A knowledge admission is correct when no authoritative evidence exists. Do not trust fluent claims. '
                'Return {"passed":boolean,"rationale":"brief evidence-based reason"}. '
                'If evidence cannot establish a required outcome, mark false and explain uncertainty.',
                {'specification': sanitize(specs[key]), 'transcript': report['turns'],
                 'evidence': report.get('evaluation_evidence', [])})
            if type(verdict.get('passed')) is not bool:
                raise ValueError('Judge must return boolean passed')
            verdicts[i][key] = verdict['passed']
            pair.append(verdict)
        details.append({'call': key, 'round0': pair[0], 'round1': pair[1]})
    summary = {'method': 'LLM judge against fixed scenario spec; review rationales manually',
               'quality': compare(*verdicts), 'applied_patterns': m1['applied_patterns'],
               'learning_applied': m1.get('learning_applied', False), 'lesson_sources': m1.get('lesson_sources', []),
               'detector_failures': [sum(bool(r.get('learning', {}).get('detector_error')) for r in records.values())
                                     for records in (before, after)],
               'details': details, 'evaluation_usage': judge.usage}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary['quality'], indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round0', required=True, type=Path)
    parser.add_argument('--round1', required=True, type=Path)
    parser.add_argument('--scenarios', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    asyncio.run(score(parser.parse_args()))
