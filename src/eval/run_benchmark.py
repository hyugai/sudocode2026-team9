#!/usr/bin/env python3
"""Run one versioned benchmark and write reproducibility metadata."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
DEFAULT_SCENARIOS = (
    REPO_ROOT / "dataset" / "iterative-refinement" / "scenarios_complete dataset"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs" / "benchmark"
TEAM_EVAL = HERE / "team_eval.py"
MEMORY_JUDGE = HERE / "memory_judge.py"
VERSION_RE = re.compile(r"^benchmark_v[1-9][0-9]*$")


def _env_float(name: str) -> float | None:
    value = os.environ.get(name, "").strip()
    return float(value) if value else None


def _git_value(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "unavailable"
    except OSError:
        return "unavailable"


def _command_text(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def _write_readme(
    path: Path,
    *,
    args: argparse.Namespace,
    started_at: str,
    finished_at: str,
    status: str,
    trace_path: Path,
    report_path: Path,
    command: list[str],
    error_turns: int,
) -> None:
    provider = os.environ.get("LLM_PROVIDER", "groq")
    model = os.environ.get("LLM_MODEL", "provider default")
    memory_mode = "durable files" if args.persist_memory else "evaluation (in memory)"
    git_commit = _git_value("rev-parse", "--short", "HEAD")
    git_dirty = bool(_git_value("status", "--porcelain").strip())
    scenario_selector = (
        args.scenario_id
        if args.scenario_id
        else (f"first {args.limit}" if args.limit else "all")
    )
    text = f"""# {args.version}

## Run status

- Status: `{status}`
- Started at: `{started_at}`
- Finished at: `{finished_at}`
- Dataset: `{Path(args.scenarios).resolve()}`
- Scenario selector: `{scenario_selector}`
- Trace: `{trace_path.name}`
- Report: `{report_path.name}`
- Turn errors: `{error_turns}`

## Parameters

- Config: `{args.config}`
- LLM provider: `{provider}`
- LLM model: `{model}`
- LLM request timeout: `{os.environ.get('LLM_REQUEST_TIMEOUT_SECONDS', '30')}` seconds
- LLM provider-internal retries: `{os.environ.get('LLM_MAX_RETRIES', '0')}`
- LLM max output tokens: `{os.environ.get('LLM_MAX_OUTPUT_TOKENS', '768')}`
- Memory mode: `{memory_mode}`
- Durable memory writes: `{args.persist_memory}`
- Memory persister: `{args.memory_persister_mode}`
- Memory root: `memory/`
- PostgreSQL eval-order cleanup: `{args.cleanup_orders}`
- Sleep between turns: `{args.sleep}` seconds
- Sleep between scenarios: `{args.sleep_scenario}` seconds
- Max retries per turn: `{args.max_retries}`
- Max turns per scenario: `{args.max_turns}`
- Team evaluator: `team_eval_v1`
- Memory Write Quality judge enabled: `{args.judge_memory}`
- Judge provider/model: `{args.judge_provider or provider}` / `{args.judge_model or model}`
- Input price / 1M tokens: `{args.input_usd_per_million}` USD
- Output price / 1M tokens: `{args.output_usd_per_million}` USD
- Tool call price: `{args.tool_call_usd}` USD
- Memory write price: `{args.memory_write_usd}` USD
- Memory storage price / MB: `{args.memory_storage_usd_per_mb}` USD
- Fixed infrastructure price / call: `{args.fixed_call_usd}` USD
- Python: `{platform.python_version()}`
- Git commit: `{git_commit}`
- Dirty worktree at run time: `{git_dirty}`

## Reproduce

Run from the repository root:

```powershell
{_command_text(command)}
```

Notes:

- API keys and `DATABASE_URL` are read from `.env` and are never copied here.
- By default, each benchmark version writes its own customer `.md` files under `memory/`; later calls read those files.
- Use `--no-persist-memory` only for a disposable in-memory smoke test.
- Orders created during evaluation are deleted by exact `order_id` after the scenario unless `--no-cleanup-orders` is used.
- MWQ uses an extra post-run LLM request per scenario only when `--judge-memory` is enabled.
- Calls-to-Close currently replays scripted `customer_turns`; it is not a dynamic customer-agent simulation.
- A one-scenario smoke test is useful for regression checking, but its aggregate metrics are not statistically representative.
"""
    path.write_text(text, encoding="utf-8")


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Run iterative-refinement scenarios into a versioned benchmark folder."
    )
    parser.add_argument("--version", required=True, help="Example: benchmark_v1")
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS))
    parser.add_argument("--scenario-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--config", choices=["full", "baseline_no_memory"], default="full")
    parser.add_argument("--llm-provider", default=None)
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--request-timeout", type=float, default=None)
    parser.add_argument("--sleep", type=float, default=20.0)
    parser.add_argument("--sleep-scenario", type=float, default=3.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument(
        "--persist-memory", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--memory-persister-mode",
        choices=["turn", "deterministic", "llm_episode", "llm_learning"],
        default=os.environ.get("MEMORY_PERSISTER_MODE", "llm_learning"),
        help="llm_learning writes learned facts/episodes/foresights; turn avoids an extra LLM call.",
    )
    parser.add_argument(
        "--cleanup-orders", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--judge-memory", action=argparse.BooleanOptionalAction, default=False
    )
    parser.add_argument("--judge-provider", default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--judge-sleep", type=float, default=0.0)
    parser.add_argument(
        "--input-usd-per-million",
        type=float,
        default=_env_float("EVAL_INPUT_USD_PER_MILLION"),
    )
    parser.add_argument(
        "--output-usd-per-million",
        type=float,
        default=_env_float("EVAL_OUTPUT_USD_PER_MILLION"),
    )
    parser.add_argument(
        "--tool-call-usd", type=float, default=_env_float("EVAL_TOOL_CALL_USD")
    )
    parser.add_argument(
        "--memory-write-usd",
        type=float,
        default=_env_float("EVAL_MEMORY_WRITE_USD"),
    )
    parser.add_argument(
        "--memory-storage-usd-per-mb",
        type=float,
        default=_env_float("EVAL_MEMORY_STORAGE_USD_PER_MB"),
    )
    parser.add_argument(
        "--fixed-call-usd", type=float, default=_env_float("EVAL_FIXED_CALL_USD")
    )
    args = parser.parse_args()

    if args.llm_provider:
        os.environ["LLM_PROVIDER"] = args.llm_provider
    if args.llm_model:
        os.environ["LLM_MODEL"] = args.llm_model
    if args.request_timeout:
        os.environ["LLM_REQUEST_TIMEOUT_SECONDS"] = str(args.request_timeout)
    os.environ["MEMORY_PERSISTER_MODE"] = args.memory_persister_mode

    if not VERSION_RE.fullmatch(args.version):
        parser.error("--version phải có dạng benchmark_v1, benchmark_v2, ...")

    run_dir = DEFAULT_OUTPUT_ROOT / args.version
    if run_dir.exists() and any(run_dir.iterdir()):
        parser.error(
            f"{run_dir} đã có dữ liệu; dùng version mới để không ghi đè benchmark cũ"
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "trace.jsonl"
    report_path = run_dir / "report.json"
    readme_path = run_dir / "README.md"
    memory_root = run_dir / "memory"
    memory_root.mkdir(exist_ok=True)

    generate_cmd = [
        sys.executable,
        str(HERE / "generate_traces.py"),
        "--scenarios",
        str(Path(args.scenarios).resolve()),
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
    if args.scenario_id:
        generate_cmd.extend(["--scenario-id", args.scenario_id])
    if args.limit is not None:
        generate_cmd.extend(["--limit", str(args.limit)])
    if args.max_turns is not None:
        generate_cmd.extend(["--max-turns", str(args.max_turns)])

    reproduce_cmd = [
        ".\\.venv\\Scripts\\python.exe",
        "src\\eval\\run_benchmark.py",
        "--version",
        args.version,
    ]
    if Path(args.scenarios).resolve() != DEFAULT_SCENARIOS.resolve():
        reproduce_cmd.extend(["--scenarios", str(Path(args.scenarios).resolve())])
    if args.scenario_id:
        reproduce_cmd.extend(["--scenario-id", args.scenario_id])
    if args.limit is not None:
        reproduce_cmd.extend(["--limit", str(args.limit)])
    if args.config != "full":
        reproduce_cmd.extend(["--config", args.config])
    if args.llm_provider:
        reproduce_cmd.extend(["--llm-provider", args.llm_provider])
    if args.llm_model:
        reproduce_cmd.extend(["--llm-model", args.llm_model])
    if args.request_timeout:
        reproduce_cmd.extend(["--request-timeout", str(args.request_timeout)])
    reproduce_cmd.extend(["--memory-persister-mode", args.memory_persister_mode])
    reproduce_cmd.append("--persist-memory" if args.persist_memory else "--no-persist-memory")
    if args.judge_memory:
        reproduce_cmd.append("--judge-memory")
    if args.judge_provider:
        reproduce_cmd.extend(["--judge-provider", args.judge_provider])
    if args.judge_model:
        reproduce_cmd.extend(["--judge-model", args.judge_model])
    if args.judge_sleep:
        reproduce_cmd.extend(["--judge-sleep", str(args.judge_sleep)])
    reproduce_cmd.append(
        "--cleanup-orders" if args.cleanup_orders else "--no-cleanup-orders"
    )
    for flag, value in (
        ("--input-usd-per-million", args.input_usd_per_million),
        ("--output-usd-per-million", args.output_usd_per_million),
        ("--tool-call-usd", args.tool_call_usd),
        ("--memory-write-usd", args.memory_write_usd),
        ("--memory-storage-usd-per-mb", args.memory_storage_usd_per_mb),
        ("--fixed-call-usd", args.fixed_call_usd),
    ):
        if value is not None:
            reproduce_cmd.extend([flag, str(value)])
    reproduce_cmd.extend([
        "--sleep", str(args.sleep),
        "--sleep-scenario", str(args.sleep_scenario),
        "--max-retries", str(args.max_retries),
    ])

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["CUSTOMER_MEMORY_ROOT"] = str(memory_root)
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    status = "running"
    _write_readme(
        readme_path,
        args=args,
        started_at=started_at,
        finished_at="pending",
        status=status,
        trace_path=trace_path,
        report_path=report_path,
        command=reproduce_cmd,
        error_turns=0,
    )

    generate = subprocess.run(generate_cmd, cwd=REPO_ROOT, env=env, check=False)
    error_turns = 0
    if trace_path.exists():
        with trace_path.open(encoding="utf-8") as trace_file:
            error_turns = sum(
                1
                for line in trace_file
                if line.strip() and json.loads(line).get("_error")
            )
    if generate.returncode == 0:
        judge_report_path = run_dir / "memory_judge.json"
        judge_return_code = 0
        if args.judge_memory:
            judge_cmd = [
                sys.executable,
                str(MEMORY_JUDGE),
                "--scenarios",
                str(Path(args.scenarios).resolve()),
                "--trace",
                str(trace_path),
                "--out",
                str(judge_report_path),
                "--sleep",
                str(args.judge_sleep),
            ]
            if args.scenario_id:
                judge_cmd.extend(["--scenario-id", args.scenario_id])
            elif args.limit is not None:
                judge_cmd.extend(["--limit", str(args.limit)])
            if args.judge_provider:
                judge_cmd.extend(["--provider", args.judge_provider])
            if args.judge_model:
                judge_cmd.extend(["--model", args.judge_model])
            judge = subprocess.run(judge_cmd, cwd=REPO_ROOT, env=env, check=False)
            judge_return_code = judge.returncode

        score_cmd = [
            sys.executable,
            str(TEAM_EVAL),
            "--scenarios",
            str(Path(args.scenarios).resolve()),
            "--trace",
            str(trace_path),
            "--out",
            str(report_path),
        ]
        if args.scenario_id:
            score_cmd.extend(["--scenario-id", args.scenario_id])
        elif args.limit is not None:
            score_cmd.extend(["--limit", str(args.limit)])
        if args.judge_memory and judge_report_path.exists():
            score_cmd.extend(["--memory-judge-report", str(judge_report_path)])
        cost_args = (
            ("--input-usd-per-million", args.input_usd_per_million),
            ("--output-usd-per-million", args.output_usd_per_million),
            ("--tool-call-usd", args.tool_call_usd),
            ("--memory-write-usd", args.memory_write_usd),
            ("--memory-storage-usd-per-mb", args.memory_storage_usd_per_mb),
            ("--fixed-call-usd", args.fixed_call_usd),
        )
        for flag, value in cost_args:
            if value is not None:
                score_cmd.extend([flag, str(value)])
        score = subprocess.run(score_cmd, cwd=REPO_ROOT, env=env, check=False)
        if score.returncode != 0:
            status = "scoring_failed"
            return_code = score.returncode
        elif error_turns or judge_return_code:
            status = "completed_with_errors"
            return_code = 2
        else:
            status = "completed"
            return_code = 0
    else:
        status = "generation_failed"
        return_code = generate.returncode

    _write_readme(
        readme_path,
        args=args,
        started_at=started_at,
        finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        status=status,
        trace_path=trace_path,
        report_path=report_path,
        command=reproduce_cmd,
        error_turns=error_turns,
    )
    print(f"[Benchmark] {status}: {run_dir}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
