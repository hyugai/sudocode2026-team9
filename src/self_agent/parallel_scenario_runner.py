"""Run at most two isolated scenario processes; never parallelize calls inside one SC."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

from .scenario_runner import load_scenarios

DEFAULT_SCENARIOS = Path(__file__).resolve().parents[2] / "dataset/transcript/M2"


def utf8_process_env():
    """Redirected Windows Python streams otherwise inherit the ANSI code page.

    Set startup encoding for this worker and its MCP children, without changing
    the caller's environment or swallowing business exceptions.
    """
    return {**os.environ, 'PYTHONUTF8':'1', 'PYTHONIOENCODING':'utf-8:backslashreplace'}


async def launch_scenario(scenario, directory, output, learning_root):
    """Child inherits normal project configuration; no shell and no credentials in argv."""
    sid = scenario["scenario_id"]
    scenario_output = output / sid
    scenario_output.mkdir(parents=True)
    command = [sys.executable, '-m', 'self_agent.scenario_runner',
               '--scenarios', str(directory.resolve()), '--scenario-id', sid,
               '--output', str(scenario_output.resolve()),
               '--learning-root', str((learning_root / sid).resolve()),
               '--runtime-root', str((scenario_output / 'runtime').resolve())]
    with (scenario_output / 'console.log').open('wb') as log:
        process = await asyncio.create_subprocess_exec(*command, stdout=log, stderr=asyncio.subprocess.STDOUT,
                                                       env=utf8_process_env())
        try:
            return await process.wait()
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
                await process.wait()
            raise


async def run_parallel(scenarios, directory, output, *, workers=2, learning_root=None, launch=launch_scenario):
    if not 1 <= workers <= 2:
        raise ValueError('workers must be 1 or 2')
    ids = [s['scenario_id'] for s in scenarios]
    if len(ids) != len(set(ids)) or any(not sid.startswith('SC-') or not sid[3:].isdigit() for sid in ids):
        raise ValueError('Scenario IDs must be unique SC-<digits>')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)  # never overwrite a previous run
    learning_root = Path(learning_root) if learning_root else output / 'learning-memory'
    semaphore = asyncio.Semaphore(workers)
    customer_locks = {}
    records = {}

    def save():
        summary = {'workers': workers, 'learning_root': str(learning_root.resolve()),
                   'scenarios': [records[sid] for sid in ids if sid in records]}
        temporary = output / 'summary.tmp'
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(output / 'summary.json')

    async def one(scenario):
        sid = scenario['scenario_id']
        # Business DB is shared: never overlap scenarios for the same customer.
        customer_key = scenario.get('customer_phone') or sid
        customer_lock = customer_locks.setdefault(customer_key, asyncio.Lock())
        async with customer_lock, semaphore:
            records[sid] = {'scenario_id': sid, 'status': 'running', 'output': str(output / sid),
                            'learning_root': str((learning_root / sid).resolve())}
            save()
            print(f'{sid}: started', flush=True)
            try:
                code = await launch(scenario, Path(directory), output, learning_root)
                records[sid].update(status='done' if code == 0 else 'failed', exit_code=code)
            except asyncio.CancelledError:
                records[sid]['status'] = 'cancelled'
                raise
            except Exception as exc:
                records[sid].update(status='failed', error=type(exc).__name__)
            finally:
                save()
            print(f"{sid}: {records[sid]['status']}", flush=True)

    tasks = [asyncio.create_task(one(scenario)) for scenario in scenarios]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return [records[sid] for sid in ids]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenarios', type=Path, default=DEFAULT_SCENARIOS,
                        help='Path to a published M2 scenario directory')
    parser.add_argument('--scenario-id', action='append', default=[])
    parser.add_argument('--limit', type=int, default=5, help='0 means all scenarios')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--output', type=Path, default=Path('outputs/self-agent/m2-parallel') / uuid.uuid4().hex)
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('--limit must be nonnegative')
    if not args.scenarios.is_dir():
        parser.error(f'M2 scenarios are unavailable at {args.scenarios}. Pass --scenarios with a published M2 dataset.')
    scenarios = load_scenarios(args.scenarios, args.scenario_id, args.limit)
    if args.list:
        for scenario in scenarios:
            print(scenario['scenario_id'], 'calls:', len(scenario['calls']))
        return
    records = asyncio.run(run_parallel(scenarios, args.scenarios, args.output, workers=args.workers))
    print(f'Summary: {args.output / "summary.json"}')
    if any(record['status'] != 'done' for record in records):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
