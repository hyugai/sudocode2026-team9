#!/usr/bin/env python3
"""Run the real agent over scenario files and serialize one trace row per turn.

Prefer ``run_benchmark.py`` for normal use. It provides versioned output,
isolated memory, scoring and reproducibility metadata around this generator.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import wave
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from jsonschema import Draft202012Validator, FormatChecker

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent          # src/eval/
REPO_ROOT = HERE.parent.parent                  # sudo_code_2026-group_9/
sys.path.insert(0, str(REPO_ROOT / "src"))
load_dotenv(REPO_ROOT / ".env")

DEFAULT_OUT_DIR = REPO_ROOT / "outputs" / "eval"
TEAM_EVAL_PATH = HERE / "team_eval.py"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Trace dependencies
# ---------------------------------------------------------------------------
from telesale_agent.core.models import Channel, ConversationState, TurnInput  # noqa: E402
from eval.model_config import configure_eval_model, permanent_provider_error  # noqa: E402
from eval.trace_extractors import (  # noqa: E402
    extract_claims,
    extract_facts_used,
    extract_questions,
)
from eval.benchmark_support import (  # noqa: E402
    DEFAULT_SCENARIOS, audio_path, load_scenario_inputs, machine_metadata,
    trace_health, validate_inputs,
)
from eval.team_eval import reference_sha256  # noqa: E402

_SCHEMAS = REPO_ROOT / "dataset" / "organizer" / "schemas"
_TRACE_VALIDATOR = Draft202012Validator(json.loads(
    (_SCHEMAS / "trace_log.schema.json").read_text(encoding="utf-8")))
_BRIEF_VALIDATOR = Draft202012Validator(json.loads(
    (_SCHEMAS / "call_brief.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker())


# ---------------------------------------------------------------------------
# Trích xuất thông tin từ TurnResult để ghi trace
# ---------------------------------------------------------------------------
def _extract_tool_calls(result) -> list[dict]:
    """Trích xuất tool calls agent đã thực thi."""
    return [
        {
            "name": call.get("name"),
            "args": call.get("args") or {},
            "result": call.get("result"),
        }
        for call in (result.tool_calls or [])
    ]


# ---------------------------------------------------------------------------
# Chạy một scenario đầy đủ (tất cả calls × turns)
# ---------------------------------------------------------------------------
async def run_scenario(
    scenario: dict,
    harness,
    config: str,
    run_id: str,
    max_turns: int | None = None,
    sleep_turn: float = 0.0,
    max_retries: int = 1,
    cleanup_orders: bool = True,
    input_kind: str = "text",
    audio_root: Path | None = None,
    include_closing_turn: bool = True,
) -> list[dict]:
    rows = []
    scenario_id = scenario["scenario_id"]
    customer_phone = scenario.get("customer_phone")
    calls_spec: dict = scenario.get("calls", {})
    created_order_ids: set[str] = set()
    persisted_facts: dict[str, dict] = defaultdict(dict)
    seeded_episodes: set[str] = set()

    def cleanup_created_orders() -> None:
        if not cleanup_orders or not created_order_ids:
            return
        try:
            from telesale_agent.adapters.db.client import db_client

            deleted = db_client.delete_orders(created_order_ids)
            print(f" [cleanup: {deleted} eval order(s)]", end="", flush=True)
        except Exception as cleanup_exc:
            if rows:
                rows[-1]["_cleanup_error"] = str(cleanup_exc)
            print(
                f"\n  [WARN] Could not clean eval orders {sorted(created_order_ids)}: "
                f"{cleanup_exc}",
                file=sys.stderr,
                flush=True,
            )

    # Each scenario is an independent experiment. Durable file memory selects
    # a scenario namespace while in-memory repositories reset their state.
    # Calls inside this scenario continue sharing the selected repository.
    select_namespace = getattr(harness.memory, "select_namespace", None)
    if callable(select_namespace):
        select_namespace(scenario_id)
    else:
        harness.reset_customer_memory()
    def seed_history(episodes):
        if episodes:
            from telesale_agent.adapters.db.client import db_client

            customer = db_client.get_customer(phone=customer_phone)
            customer_id = customer.get("customer_id") if customer.get("found") else None
            if not customer_id:
                raise ValueError(f"Cannot seed history for {scenario_id}: customer is absent or ambiguous")
            for episode in episodes:
                marker = episode.get("session_id") or json.dumps(episode, sort_keys=True)
                if marker in seeded_episodes:
                    continue
                summary = (
                    f"Channel: {episode.get('channel', 'unknown')}\n"
                    f"Outcome: {episode.get('outcome', 'unknown')}\n"
                    f"Summary: {episode.get('summary', '')}"
                )
                harness.memory.record_episode(
                    customer_id, summary, occurred_on=episode.get("date"),
                    source_id=episode.get("session_id"),
                )
                seeded_episodes.add(marker)

    if config == "full":
        seed_history(scenario.get("seed_history", []))
    previous_call_date = date(2026, 10, 15)

    for call_key in sorted(calls_spec.keys()):  # call_1, call_2, ...
        spec = calls_spec[call_key]
        prior_facts = {cid: facts.copy() for cid, facts in persisted_facts.items()}
        if config == "full":
            try:
                seed_history(spec.get("seed_history", []))
            except Exception:
                cleanup_created_orders()
                raise
        raw_input_mode = spec.get("input_mode")
        if raw_input_mode in {"clean", "asr_transcript", "chat_teencode"}:
            input_mode = raw_input_mode
        elif raw_input_mode == "noisy" or spec.get("customer_turns_asr") or input_kind == "audio":
            input_mode = "asr_transcript"
        else:
            input_mode = "clean"
        customer_turns: list[str] = (
            spec.get("customer_turns_asr")
            if spec.get("customer_turns_asr")
            else spec.get("customer_turns", [])
        )
        reference_turns = spec.get("customer_turns") or []
        if spec.get("call_date"):
            current_call_date = date.fromisoformat(spec["call_date"])
        else:
            current_call_date = previous_call_date + timedelta(
                days=int(spec.get("days_later", 0))
            )
        previous_call_date = current_call_date
        call_date = current_call_date.isoformat()
        conversation_id = f"{run_id}__{scenario_id}__{call_key}"
        conv_state = ConversationState(conversation_id=conversation_id)

        turn_specs = [
            (turn_idx, customer_text, False)
            for turn_idx, customer_text in enumerate(customer_turns, start=1)
        ]
        if include_closing_turn:
            turn_specs.append((len(customer_turns) + 1, "", True))

        for turn_idx, customer_text, is_closing_turn in turn_specs:
            if sleep_turn > 0 and (turn_idx > 1 or call_key != "call_1"):
                await asyncio.sleep(sleep_turn)
            t0 = time.perf_counter()
            try:
                audio_file = None
                audio_info = None
                if input_kind == "audio" and not is_closing_turn:
                    if audio_root is None:
                        raise ValueError("audio_root is required for audio evaluation")
                    audio_file = audio_path(audio_root, scenario_id, call_key, turn_idx)
                    with wave.open(str(audio_file), "rb") as wav:
                        audio_info = {"path":str(audio_file), "duration_seconds":wav.getnframes()/wav.getframerate()}
                turn_metadata = {
                    "call_date": call_date,
                    "call_key": call_key,
                    "scenario_id": scenario_id,
                }
                if is_closing_turn:
                    turn_metadata["closing_turn"] = True
                turn_input = TurnInput(
                    conversation_id=conversation_id,
                    text=None if audio_file else customer_text,
                    audio=audio_file.read_bytes() if audio_file else None,
                    channel=Channel.CHAT,
                    customer_hint=customer_phone,
                    metadata=turn_metadata,
                )
                result = None
                for attempt in range(max_retries):
                    try:
                        # Harness arrival is the evaluation boundary; dataset
                        # file loading and client/UI time are outside it.
                        turn_input.metadata["_latency_started_at"] = time.perf_counter()
                        result = await harness.run_turn(turn_input, conv_state)
                        break
                    except Exception as turn_exc:
                        err_str = str(turn_exc)
                        is_request_too_large = (
                            getattr(turn_exc,"status_code",None) == 413
                            or "request too large" in err_str.lower()
                            or "request_too_large" in err_str.lower()
                        )
                        is_rate_limit = (
                            "rate_limit" in err_str.lower()
                            or "429" in err_str
                            or "tpm" in err_str.lower()
                            or "tokens per minute" in err_str.lower()
                            or "RateLimitError" in type(turn_exc).__name__
                        )
                        is_transient_provider_error = (
                            "503" in err_str
                            or "504" in err_str
                            or "unavailable" in err_str.lower()
                            or "deadline_exceeded" in err_str.lower()
                            or "high demand" in err_str.lower()
                        )
                        if is_request_too_large:
                            print(
                                f"\n  [CONTEXT LIMIT] {scenario_id}/{call_key}/turn{turn_idx}: "
                                f"{err_str}",
                                file=sys.stderr,
                                flush=True,
                            )
                            raise turn_exc
                        if (is_rate_limit or is_transient_provider_error) and attempt < max_retries - 1:
                            m = re.search(r"try again in ([\d\.]+)s", err_str, re.I)
                            wait_sec = float(m.group(1)) + 1.0 if m else min(60.0, 10.0 * (2 ** attempt))
                            reason = "RATE LIMIT" if is_rate_limit else "TRANSIENT PROVIDER"
                            print(
                                f"\n  [{reason}] {scenario_id}/{call_key}/turn{turn_idx}: "
                                f"Tạm nghỉ {wait_sec:.1f}s trước khi thử lại "
                                f"(lần {attempt + 1}/{max_retries})...",
                                file=sys.stderr,
                                flush=True,
                            )
                            await asyncio.sleep(wait_sec)
                        else:
                            raise turn_exc

                conv_state = result.state
                total_ms = int((time.perf_counter() - t0) * 1000)
                latency = dict(getattr(result, "latency", {}) or {})
                if not latency:
                    latency = {"ttft_ms":0,"total_ms":total_ms,"ttfa_ms":None,"measurement_mode":"unavailable"}
                for key in ("ttft_ms", "total_ms", "ttfa_ms", "call_brief_ms"):
                    if latency.get(key) is not None:
                        latency[key] = round(latency[key])

                tool_calls = _extract_tool_calls(result)
                created_order_ids.update(
                    str(call["result"]["order_id"])
                    for call in tool_calls
                    if call.get("name") == "order.create"
                    and isinstance(call.get("result"), dict)
                    and call["result"].get("order_id")
                )
                is_baseline = config == "baseline_no_memory"
                response_text = result.response_text or ""
                trace_memory_writes = [] if is_baseline else (result.memory_writes or [])
                customer_id = getattr(getattr(result, "call_brief", None), "customer_id", None)
                for write in trace_memory_writes:
                    cid, key = write.get("customer_id") or customer_id, write.get("key")
                    if not cid or not key:
                        continue
                    if write.get("op") == "delete":
                        persisted_facts[cid].pop(key, None)
                    elif write.get("op") in {"set", "supersede"} and "value" in write:
                        persisted_facts[cid][key] = write["value"]
                row = {
                    "run_id": run_id,
                    "config": config,
                    "scenario_id": scenario_id,
                    "call": call_key,
                    "turn": turn_idx,
                    "customer_text": "" if is_closing_turn else turn_input.metadata.get("raw_asr_transcript", customer_text),
                    "reference_customer_text": (
                        ""
                        if is_closing_turn
                        else (reference_turns[turn_idx - 1] if turn_idx <= len(reference_turns) else customer_text)
                    ),
                    "normalized_customer_text": "" if is_closing_turn else turn_input.text,
                    "agent_text": response_text,
                    "questions": extract_questions(response_text),
                    "facts_used": (
                        []
                        if is_baseline or call_key == "call_1"
                        else extract_facts_used(
                            response_text, tool_calls, prior_facts.get(customer_id, {}),
                            current_brief=result.call_brief,
                        )
                    ),
                    "claims": extract_claims(
                        tool_calls,
                        call_date=call_date,
                        response_text=response_text,
                    ),
                    "tool_calls": tool_calls,
                    "memory_writes": trace_memory_writes,
                    "usage": result.usage,
                    "customer_input_mode": input_mode,
                    "input_kind": input_kind,
                    "latency": latency,
                    "runner_total_ms": total_ms,
                }
                if audio_info:
                    row["audio"] = audio_info
                if turn_idx == 1:
                    row["call_brief_latency_ms"] = latency.get("call_brief_ms")
                    if not is_baseline and getattr(result.call_brief, "generated_at", None):
                        row["call_brief"] = result.call_brief.to_btc()
                        _BRIEF_VALIDATOR.validate(row["call_brief"])

            except Exception as exc:
                total_ms = int((time.perf_counter() - t0) * 1000)
                error_text = str(exc) or type(exc).__name__
                print(f"\n  [ERROR] {scenario_id}/{call_key}/turn{turn_idx}: {error_text}", file=sys.stderr)
                row = {
                    "run_id": run_id,
                    "config": config,
                    "scenario_id": scenario_id,
                    "call": call_key,
                    "turn": turn_idx,
                    "customer_text": "" if is_closing_turn else customer_text,
                    "agent_text": "",
                    "questions": [],
                    "facts_used": [],
                    "claims": [],
                    "tool_calls": [],
                    "memory_writes": [],
                    "usage": getattr(exc,"telesale_usage",None) or {
                        "requests": 0,
                        "failed_requests": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                    },
                    "customer_input_mode": input_mode,
                    "input_kind": input_kind,
                    "latency": {"ttft_ms": 0, "total_ms": total_ms, "ttfa_ms": None,
                                "measurement_mode": "unavailable"},
                    "_error": error_text,
                    "_fatal_provider_error": permanent_provider_error(exc),
                }
                if getattr(exc,"telesale_profile",None):
                    row["latency"]["profile"] = exc.telesale_profile
            try:
                _TRACE_VALIDATOR.validate(row)
            except Exception:
                cleanup_created_orders()
                raise
            rows.append(row)
            if row.get("_fatal_provider_error"):
                cleanup_created_orders()
                return rows
            if max_turns is not None and len(rows) >= max_turns:
                cleanup_created_orders()
                return rows
    cleanup_created_orders()
    return rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main(*, submission=False):
    parser = argparse.ArgumentParser(
        description="Chạy AI Agent thật qua BTC scenarios và ghi trace JSONL."
    )
    parser.add_argument(
        "--scenarios",
        default=str(DEFAULT_SCENARIOS),
        required=submission,
        help=f"Thư mục chứa các scenario JSON (default: {DEFAULT_SCENARIOS})",
    )
    parser.add_argument(
        "--config",
        default="full",
        required=submission,
        choices=["full", "baseline_no_memory"],
        help="Config name ghi vào trace (default: full)",
    )
    parser.add_argument("--run-id", default="team_run", dest="run_id",
                        help="Tên định danh của run (default: team_run)")
    parser.add_argument("--out", default=None, required=submission,
                        help="Đường dẫn JSONL output (default: outputs/eval/<run_id>.jsonl)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Chỉ chạy N scenario đầu (để test nhanh)")
    parser.add_argument("--scenario-id", default=None, dest="scenario_id",
                        help="Chỉ chạy một scenario cụ thể, vd: SC-001")
    parser.add_argument("--input-kind", choices=["text","audio"], default="text")
    parser.add_argument("--llm-provider",default=None)
    parser.add_argument("--llm-model",default=None)
    parser.add_argument("--audio-root", type=Path, help="WAV directory with a sibling manifest.jsonl")
    parser.add_argument("--preflight-only", action="store_true", help="Validate every selected input and exit.")
    parser.add_argument(
        "--scenario-ids",
        nargs="+",
        default=None,
        dest="scenario_ids",
        help="Chạy danh sách scenario cụ thể, vd: --scenario-ids SC-001 SC-002",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Giới hạn tổng số turn mỗi scenario để smoke test nhanh",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Số giây nghỉ giữa mỗi turn (default: 0.0)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help=(
            "Số lần thử tối đa cho mỗi turn (default: 1 = không tự retry). "
            "Tránh chạy lại cả NLU + agent khi provider báo 429."
        ),
    )
    parser.add_argument(
        "--sleep-scenario",
        type=float,
        default=0.0,
        help="Số giây nghỉ giữa mỗi scenario (default: 0.0)",
    )
    parser.add_argument(
        "--persist-memory",
        action=argparse.BooleanOptionalAction,
        default=_env_flag("EVAL_PERSIST_MEMORY", True),
        help=(
            "Write benchmark memory to CUSTOMER_MEMORY_ROOT (default: true). "
            "Use --no-persist-memory for an in-memory smoke test."
        ),
    )
    parser.add_argument(
        "--cleanup-orders",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Delete PostgreSQL orders created by this evaluation scenario after "
            "its calls finish (default: true)."
        ),
    )
    parser.add_argument(
        "--closing-turn",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Append one post-call agent closing turn with empty customer_text "
            "after each call's last customer turn (default: true)."
        ),
    )
    args = parser.parse_args()
    if args.input_kind == "audio" and args.audio_root is None:
        parser.error("--input-kind audio requires --audio-root and a matching scenario dataset")
    model = configure_eval_model(args.llm_provider, args.llm_model)

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than zero")
    if args.max_turns is not None and args.max_turns <= 0:
        parser.error("--max-turns must be greater than zero")
    if args.max_retries <= 0:
        parser.error("--max-retries must be greater than zero")
    if args.sleep < 0 or args.sleep_scenario < 0:
        parser.error("--sleep and --sleep-scenario cannot be negative")

    scenarios_dir = Path(args.scenarios)
    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"{args.run_id}.jsonl"
    try:
        selected = load_scenario_inputs(scenarios_dir)
        ids = args.scenario_ids or ([args.scenario_id] if args.scenario_id else list(selected))
        selected = {sid: selected[sid] for sid in ids[:args.limit]}
        selection = validate_inputs(selected, args.audio_root if args.input_kind == "audio" else None)
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    print(f"[Preflight] {json.dumps(selection, ensure_ascii=False)}", flush=True)
    if args.preflight_only:
        return 0

    metadata_path = out_path.with_suffix(".metadata.json")
    if submission:
        memory_root = out_path.with_name(f"{out_path.stem}_memory")
        if out_path.exists() or metadata_path.exists() or memory_root.exists():
            parser.error("Output exists. Choose a new --out path.")
        if not model.api_key:
            parser.error(f"No API key configured for {model.provider}")
        os.environ["CUSTOMER_MEMORY_ROOT"] = str(memory_root.resolve())
        os.environ["CUSTOMER_MEMORY_BACKEND"] = "file"
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[Runner] Config         : {args.config}")
    print(f"[Runner] Run ID         : {args.run_id}")
    print(f"[Runner] Scenarios      : {len(selected)} files")
    print(f"[Runner] Sleep turn     : {args.sleep}s | Sleep scenario: {args.sleep_scenario}s")
    print(f"[Runner] Persist memory : {args.persist_memory}")
    print(f"[Runner] Cleanup orders : {args.cleanup_orders}")
    print(f"[Runner] Output         : {out_path}")
    print()

    print("[Runner] Khởi động Agent Harness...")
    from telesale_agent.bootstrap import build_deepagent_harness_async

    memory_mode = (
        ("durable" if args.persist_memory else "evaluation")
        if args.config == "full"
        else "disabled"
    )
    harness = await build_deepagent_harness_async(memory_mode=memory_mode)
    print("[Runner] Agent sẵn sàng.\n")

    total_rows = 0
    failures = 0
    trace = defaultdict(list)
    try:
        with out_path.open("x" if submission else "w", encoding="utf-8") as out_f:
            for i, (sid, scenario) in enumerate(selected.items(), start=1):
                if i > 1 and args.sleep_scenario > 0:
                    await asyncio.sleep(args.sleep_scenario)
                print(f"[{i:3d}/{len(selected)}] {sid} starting...", flush=True)

                t0 = time.perf_counter()
                try:
                    rows = await run_scenario(
                        scenario,
                        harness,
                        args.config,
                        args.run_id,
                        max_turns=args.max_turns,
                        sleep_turn=args.sleep,
                        max_retries=args.max_retries,
                        cleanup_orders=args.cleanup_orders,
                        input_kind=args.input_kind,
                        audio_root=args.audio_root,
                        include_closing_turn=args.closing_turn,
                    )
                    elapsed = time.perf_counter() - t0
                    print(f"[{i:3d}/{len(selected)}] {sid}: ✓ {len(rows)} turns, {elapsed:.1f}s", flush=True)
                    for row in rows:
                        row["latency_warmup"] = total_rows < 3
                        total_rows += 1
                        failures += int("_error" in row)
                        trace[(sid, row["call"])].append(row)
                        out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        out_f.flush()
                    if any(row.get("_fatal_provider_error") for row in rows):
                        print("[Runner] Stopping: provider billing/auth/model access needs attention.",flush=True)
                        break
                except Exception as scenario_exc:
                    failures += 1
                    elapsed = time.perf_counter() - t0
                    print(f"[{i:3d}/{len(selected)}] {sid}: FAILED ({elapsed:.1f}s) - {scenario_exc}", flush=True)
    finally:
        await harness.__aexit__(None, None, None)

    health = trace_health(selected, trace)
    if submission:
        metadata = {
            "config": args.config,
            "selection": selection,
            "trace_health": health,
            "provider": model.provider,
            "model": model.model,
            "request_timeout_seconds": model.timeout,
            "model_max_retries": model.max_retries,
            "max_output_tokens": model.max_output_tokens,
                "request_interval_seconds": float(os.environ["EVAL_REQUEST_INTERVAL_SECONDS"]),
                "thinking_level": os.environ.get("LLM_THINKING_LEVEL"),
                "nlu_thinking_level": os.environ.get("NLU_THINKING_LEVEL"),
                "deepagent_thinking_level": os.environ.get("DEEPAGENT_THINKING_LEVEL"),
                "memory_persister_mode": os.environ.get("MEMORY_PERSISTER_MODE", "llm_learning"),
                "custom_endpoint": bool(os.environ.get("LLM_API_ENDPOINT")),
            "hardware": machine_metadata(),
                "reference_sha256": reference_sha256(),
                "git_commit": subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True,
                ).stdout.strip(),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "dataset_sha256": hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest(),
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = out_path.with_name(f"{out_path.stem}_report.json")
    if args.scenario_ids:
        selector = f" --scenario-ids {','.join(args.scenario_ids)}"
    elif args.scenario_id:
        selector = f" --scenario-id {args.scenario_id}"
    elif args.limit is not None:
        selector = f" --limit {args.limit}"
    else:
        selector = ""
    print(f"\n[Runner] Hoàn thành! {total_rows} rows → {out_path}")
    print("\n[Runner] Để chấm điểm bằng team evaluator, chạy:")
    print(
        f'  python "{TEAM_EVAL_PATH}" --scenarios "{scenarios_dir}" '
        f'--trace "{out_path}"{selector} --out "{report_path}"'
    )
    return 2 if failures or (submission and not health["valid"]) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
