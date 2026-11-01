#!/usr/bin/env python3
"""Run isolated benchmark scenarios with a small parallel worker pool.

The scheduler groups scenarios by customer phone before balancing work. A phone
group is assigned to exactly one worker, so two concurrent scenarios cannot
mutate/query orders for the same CRM identity. Each scenario receives its own
CUSTOMER_MEMORY_ROOT and its own process/harness, preventing durable markdown
memory from leaking between otherwise independent scenarios.

After all workers finish, scenario traces are merged in dataset order and the
existing team evaluator creates one aggregate report.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0,str(REPO_ROOT / "src"))
from eval.model_config import configure_eval_model
DEFAULT_SCENARIOS = (
    REPO_ROOT / "dataset" / "iterative-refinement" / "scenarios_complete dataset"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs" / "benchmark"
GENERATE_TRACES = HERE / "generate_traces.py"
TEAM_EVAL = HERE / "team_eval.py"
VERSION_RE = re.compile(r"^benchmark_v[1-9][0-9]*$")


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    phone: str
    turns: int
    path: Path
    dataset_index: int


@dataclass
class Partition:
    index: int
    scenarios: list[ScenarioSpec]
    turns: int = 0


def _load_scenarios(
    directory: Path,
    limit: int | None,
    scenario_ids: list[str] | None = None,
) -> list[ScenarioSpec]:
    files = sorted(
        path for path in directory.glob("*.json") if not path.name.startswith("_")
    )
    if scenario_ids:
        targets = {s.strip().casefold() for s in scenario_ids if s.strip()}
        files = [
            p
            for p in files
            if p.stem.casefold() in targets or p.name.casefold() in targets
        ]
    if limit is not None:
        files = files[:limit]
    if not files:
        raise ValueError(f"Không tìm thấy scenario JSON phù hợp trong {directory}")

    scenarios: list[ScenarioSpec] = []
    for index, path in enumerate(files):
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenario_id = str(payload.get("scenario_id") or path.stem)
        phone = str(payload.get("customer_phone") or f"missing:{scenario_id}")
        calls = payload.get("calls") or {}
        turns = sum(
            len(call.get("customer_turns_asr") or call.get("customer_turns") or [])
            for call in calls.values()
            if isinstance(call, dict)
        )
        scenarios.append(
            ScenarioSpec(
                scenario_id=scenario_id,
                phone=phone,
                turns=turns,
                path=path,
                dataset_index=index,
            )
        )
    return scenarios


def partition_by_phone(
    scenarios: list[ScenarioSpec], workers: int
) -> list[Partition]:
    """Balance turn weights while keeping every repeated phone on one worker."""
    phone_groups: dict[str, list[ScenarioSpec]] = {}
    for scenario in scenarios:
        phone_groups.setdefault(scenario.phone, []).append(scenario)

    groups = sorted(
        phone_groups.values(),
        key=lambda group: (
            -sum(item.turns for item in group),
            min(item.dataset_index for item in group),
        ),
    )
    partitions = [Partition(index=index + 1, scenarios=[]) for index in range(workers)]
    for group in groups:
        target = min(partitions, key=lambda item: (item.turns, item.index))
        target.scenarios.extend(group)
        target.turns += sum(item.turns for item in group)

    for partition in partitions:
        partition.scenarios.sort(key=lambda item: item.dataset_index)
    return partitions


def _git_value(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return "unavailable"
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def _command_text(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def _build_worker_generate_command(
    args: argparse.Namespace,
    scenarios: list[ScenarioSpec],
    trace_path: Path,
) -> list[str]:
    command = [
        sys.executable,
        str(GENERATE_TRACES),
        "--scenarios",
        str(Path(args.scenarios).resolve()),
        "--scenario-ids",
        *[scenario.scenario_id for scenario in scenarios],
        "--config",
        args.config,
        "--run-id",
        args.version,
        "--out",
        str(trace_path),
        "--sleep",
        str(args.sleep),
        "--sleep-scenario",
        str(args.sleep_scenario),
        "--max-retries",
        str(args.max_retries),
        "--persist-memory" if args.persist_memory else "--no-persist-memory",
        "--cleanup-orders" if args.cleanup_orders else "--no-cleanup-orders",
    ]
    if args.max_turns is not None:
        command.extend(["--max-turns", str(args.max_turns)])
    return command


def _worker_run(
    partition: Partition,
    args: argparse.Namespace,
    run_dir: Path,
    base_env: dict[str, str],
    print_lock: threading.Lock,
) -> dict[str, Any]:
    part_dir = run_dir / f"part_{partition.index}"
    part_trace = part_dir / "trace.jsonl"
    worker_log = part_dir / "worker.log"
    memory_dir = part_dir / "memory"
    part_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)

    env = dict(base_env)
    env["CUSTOMER_MEMORY_ROOT"] = str(memory_dir.resolve())
    command = _build_worker_generate_command(args, partition.scenarios, part_trace)
    scenario_ids = [s.scenario_id for s in partition.scenarios]

    with print_lock:
        print(
            f"[worker {partition.index}] Khởi động {len(scenario_ids)} scenarios: "
            f"{', '.join(scenario_ids)}",
            flush=True,
        )

    started = time.perf_counter()
    failures: list[dict[str, Any]] = []
    completed = 0

    with worker_log.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log_file.write(line)
            log_file.flush()
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("[Runner] Khởi động") or stripped.startswith("[Runner] Agent sẵn sàng"):
                with print_lock:
                    print(f"[worker {partition.index}] {stripped}", flush=True)
            elif re.search(r"\[\s*\d+/\s*\d+\]", stripped):
                with print_lock:
                    print(f"[worker {partition.index}] {stripped}", flush=True)
            elif stripped.startswith("[ERROR]") or stripped.startswith("[CONTEXT LIMIT]"):
                with print_lock:
                    print(f"[worker {partition.index}] {stripped}", flush=True)

        proc.wait()

    elapsed = time.perf_counter() - started

    seen_scenarios: set[str] = set()
    if part_trace.exists():
        for line in part_trace.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                sid = row.get("scenario_id")
                if sid:
                    seen_scenarios.add(str(sid))
            except Exception:
                pass

    for scenario in partition.scenarios:
        if scenario.scenario_id in seen_scenarios:
            completed += 1
        else:
            failures.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "return_code": proc.returncode,
                    "log": str(worker_log.relative_to(run_dir)),
                }
            )

    with print_lock:
        status_marker = "done" if not failures else "has failures"
        print(
            f"[worker {partition.index}] {status_marker}: "
            f"{completed}/{len(partition.scenarios)} scenarios ({elapsed:.1f}s)",
            flush=True,
        )

    return {
        "worker": partition.index,
        "completed": completed,
        "failed": failures,
        "trace": part_trace,
    }


def _merge_traces(
    scenarios: list[ScenarioSpec], worker_results: list[dict[str, Any]], out: Path
) -> tuple[int, int]:
    scenario_order = {item.scenario_id: item.dataset_index for item in scenarios}
    rows: list[dict[str, Any]] = []
    for result in worker_results:
        path = Path(result["trace"])
        if not path.exists():
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc

    def key(row: dict[str, Any]) -> tuple[int, str, int]:
        return (
            scenario_order.get(str(row.get("scenario_id")), len(scenario_order)),
            str(row.get("call") or ""),
            int(row.get("turn") or 0),
        )

    rows.sort(key=key)
    with out.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows), sum(1 for row in rows if row.get("_error"))


def _write_partition_manifest(
    path: Path, partitions: list[Partition]
) -> None:
    payload = {
        "strategy": "group_by_customer_phone_then_balance_by_turns",
        "partitions": [
            {
                "worker": partition.index,
                "turns": partition.turns,
                "scenario_count": len(partition.scenarios),
                "scenarios": [item.scenario_id for item in partition.scenarios],
            }
            for partition in partitions
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_readme(
    path: Path,
    *,
    args: argparse.Namespace,
    partitions: list[Partition],
    started_at: str,
    finished_at: str,
    status: str,
    rows: int,
    error_turns: int,
    failures: list[dict[str, Any]],
) -> None:
    reproduce = [
        ".\\.venv\\Scripts\\python.exe",
        "src\\eval\\run_parallel_benchmark.py",
        *sys.argv[1:],
    ]
    partition_lines = "\n".join(
        f"- Worker {part.index}: {len(part.scenarios)} scenarios, {part.turns} turns"
        for part in partitions
    )
    memory_backend = os.environ.get("CUSTOMER_MEMORY_BACKEND", "file")
    memory_location = (
        f"object-storage prefix `{os.environ.get('CUSTOMER_MEMORY_PREFIX', 'users')}`"
        if args.persist_memory and memory_backend == "object_storage"
        else "`part_<N>/memory/<SCENARIO_ID>/`"
    )
    text = f"""# {args.version} — parallel benchmark

## Run status

- Status: `{status}`
- Started at: `{started_at}`
- Finished at: `{finished_at}`
- Dataset: `{Path(args.scenarios).resolve()}`
- Workers: `{args.workers}`
- Trace rows: `{rows}`
- Turn errors: `{error_turns}`
- Worker/scenario process failures: `{len(failures)}`

## Partitioning

Scenarios are grouped by `customer_phone`, then balanced by total customer
turns. The same phone never runs in two workers. Every scenario uses an isolated
memory location at {memory_location}.

{partition_lines}

See `partitions.json` for the scenario assignment and each
`part_<N>/worker.log` for raw runner output.

## Parameters

- Config: `{args.config}`
- Response mode: `non_streaming` (TTFT = Total at complete guarded answer; persistence excluded)
- Provider/model: `{os.environ.get('LLM_PROVIDER', 'groq')}` / `{os.environ.get('LLM_MODEL', 'provider default')}`
- Request timeout: `{os.environ.get('LLM_REQUEST_TIMEOUT_SECONDS', '30')}` seconds
- Max output tokens: `{os.environ.get('LLM_MAX_OUTPUT_TOKENS', '1024')}`
- Thinking level: `{os.environ.get('LLM_THINKING_LEVEL') or 'provider default'}`
- Memory persister: `{args.memory_persister_mode}`
- Memory backend: `{memory_backend}`
- Object-storage prefix: `{os.environ.get('CUSTOMER_MEMORY_PREFIX', 'users') if memory_backend == 'object_storage' else 'n/a'}`
- Durable memory: `{args.persist_memory}`
- Cleanup eval orders: `{args.cleanup_orders}`
- Sleep between turns: `{args.sleep}` seconds
- Sleep between scenarios in one worker: `{args.sleep_scenario}` seconds
- Max retries per turn: `{args.max_retries}`
- Max turns per scenario: `{args.max_turns}`
- Python: `{platform.python_version()}`
- Git commit: `{_git_value('rev-parse', '--short', 'HEAD')}`
- Dirty worktree at run time: `{bool(_git_value('status', '--porcelain').strip())}`

## Reproduce

```powershell
{_command_text(reproduce)}
```

## Artifacts

- `trace.jsonl`: merged trace in dataset order.
- `report.json`: aggregate report for the selected scenarios.
- `partitions.json`: worker assignment without duplicating phone values.
- `part_<N>/trace.jsonl`: trace for one worker.
- `part_<N>/memory/<SCENARIO_ID>/`: isolated `.md` memory for audit.
- `part_<N>/worker.log`: stdout/stderr of worker process.
"""
    path.write_text(text, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run scenarios in parallel while isolating memory and keeping "
            "repeated customer phones on one worker."
        )
    )
    parser.add_argument("--version", required=True, help="Example: benchmark_v10")
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--scenario-ids",
        default=None,
        help="Comma-separated scenario IDs to run (e.g. SC-001,SC-011).",
    )
    parser.add_argument(
        "--config", choices=["full", "baseline_no_memory"], default="full"
    )
    parser.add_argument("--llm-provider", default=None)
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--request-timeout", type=float, default=None)
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument(
        "--thinking-level",
        choices=["minimal", "low", "medium", "high"],
        default=None,
        help="Gemini 3 thinking level; thinking tokens are billed as output.",
    )
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--sleep-scenario", type=float, default=0.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument(
        "--persist-memory", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--memory-persister-mode",
        choices=["turn", "deterministic", "llm_episode", "llm_learning"],
        default=os.environ.get("MEMORY_PERSISTER_MODE", "llm_learning"),
    )
    parser.add_argument(
        "--cleanup-orders", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Print the phone-safe partition plan without creating output or calling APIs.",
    )
    return parser


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = _parser()
    args = parser.parse_args()

    if not VERSION_RE.fullmatch(args.version):
        parser.error("--version phải có dạng benchmark_v1, benchmark_v2, ...")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than zero")
    if args.max_turns is not None and args.max_turns <= 0:
        parser.error("--max-turns must be greater than zero")
    if args.max_retries <= 0:
        parser.error("--max-retries must be greater than zero")
    if args.sleep < 0 or args.sleep_scenario < 0:
        parser.error("sleep values cannot be negative")
    if args.request_timeout is not None and args.request_timeout <= 0:
        parser.error("--request-timeout must be greater than zero")
    if args.max_output_tokens is not None and args.max_output_tokens <= 0:
        parser.error("--max-output-tokens must be greater than zero")

    scenario_ids = (
        [s.strip() for s in args.scenario_ids.split(",") if s.strip()]
        if args.scenario_ids
        else None
    )
    scenarios_dir = Path(args.scenarios).resolve()
    scenarios = _load_scenarios(scenarios_dir, args.limit, scenario_ids)
    workers = min(args.workers, len(scenarios))
    args.workers = workers
    partitions = partition_by_phone(scenarios, workers)

    print(
        f"[Parallel] {len(scenarios)} scenarios / "
        f"{sum(item.turns for item in scenarios)} turns / {workers} workers"
    )
    for partition in partitions:
        print(
            f"  worker {partition.index}: {len(partition.scenarios)} scenarios, "
            f"{partition.turns} turns"
        )
    if args.plan_only:
        for partition in partitions:
            ids = ", ".join(item.scenario_id for item in partition.scenarios)
            print(f"  worker {partition.index} scenarios: {ids}")
        return 0

    run_dir = DEFAULT_OUTPUT_ROOT / args.version
    if run_dir.exists() and any(run_dir.iterdir()):
        parser.error(f"{run_dir} đã có dữ liệu; hãy dùng benchmark version mới")
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "trace.jsonl"
    report_path = run_dir / "report.json"
    readme_path = run_dir / "README.md"
    _write_partition_manifest(run_dir / "partitions.json", partitions)

    configure_eval_model(args.llm_provider,args.llm_model)
    if args.request_timeout is not None:
        os.environ["LLM_REQUEST_TIMEOUT_SECONDS"] = str(args.request_timeout)
    if args.max_output_tokens is not None:
        os.environ["LLM_MAX_OUTPUT_TOKENS"] = str(args.max_output_tokens)
    if args.thinking_level:
        os.environ["LLM_THINKING_LEVEL"] = args.thinking_level
    os.environ["MEMORY_PERSISTER_MODE"] = args.memory_persister_mode

    base_env = os.environ.copy()
    source_root = str((REPO_ROOT / "src").resolve())
    existing_pythonpath = base_env.get("PYTHONPATH", "")
    base_env["PYTHONPATH"] = (
        source_root
        if not existing_pythonpath
        else source_root + os.pathsep + existing_pythonpath
    )
    base_env["PYTHONIOENCODING"] = "utf-8"

    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    _write_readme(
        readme_path,
        args=args,
        partitions=partitions,
        started_at=started_at,
        finished_at="pending",
        status="running",
        rows=0,
        error_turns=0,
        failures=[],
    )

    print_lock = threading.Lock()
    worker_results: list[dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    _worker_run,
                    partition,
                    args,
                    run_dir,
                    base_env,
                    print_lock,
                )
                for partition in partitions
            ]
            for future in as_completed(futures):
                worker_results.append(future.result())
    except KeyboardInterrupt:
        print("\n[Parallel] Interrupted. Child scenario processes may need to finish.")
        return 130

    worker_results.sort(key=lambda item: int(item["worker"]))
    failures = [
        failure
        for result in worker_results
        for failure in result.get("failed", [])
    ]
    row_count, error_turns = _merge_traces(scenarios, worker_results, trace_path)

    score_command = [
        sys.executable,
        str(TEAM_EVAL),
        "--scenarios",
        str(scenarios_dir),
        "--trace",
        str(trace_path),
        "--out",
        str(report_path),
    ]
    if args.limit is not None:
        score_command.extend(["--limit", str(args.limit)])
    if args.scenario_ids:
        score_command.extend(["--scenario-ids", args.scenario_ids])

    score = subprocess.run(
        score_command,
        cwd=REPO_ROOT,
        env=base_env,
        check=False,
    )
    if failures:
        status = "worker_failed"
        return_code = 2
    elif score.returncode != 0:
        status = "scoring_failed"
        return_code = score.returncode
    elif error_turns:
        status = "completed_with_errors"
        return_code = 2
    else:
        status = "completed"
        return_code = 0

    finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
    _write_readme(
        readme_path,
        args=args,
        partitions=partitions,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        rows=row_count,
        error_turns=error_turns,
        failures=failures,
    )
    print(
        f"[Parallel] status={status} rows={row_count} "
        f"turn_errors={error_turns} failures={len(failures)}"
    )
    print(f"[Parallel] trace: {trace_path}")
    print(f"[Parallel] report: {report_path}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
