#!/usr/bin/env python3
"""Run the real agent over scenario files and serialize one trace row per turn.

Prefer ``run_benchmark.py`` for normal use. It provides versioned output,
isolated memory, scoring and reproducibility metadata around this generator.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
import wave
from datetime import date, timedelta
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

DEFAULT_SCENARIOS_DIR = (
    REPO_ROOT
    / "dataset"
    / "iterative-refinement"
    / "scenarios_complete dataset"
)
DEFAULT_OUT_DIR = REPO_ROOT / "outputs" / "eval"
TEAM_EVAL_PATH = HERE / "team_eval.py"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Import agent (lazy để lỗi import hiện rõ)
# ---------------------------------------------------------------------------
from telesale_agent.bootstrap import build_deepagent_harness_async  # noqa: E402
from telesale_agent.adapters.db.client import db_client  # noqa: E402
from telesale_agent.core.models import Channel, ConversationState, TurnInput  # noqa: E402
from eval.trace_extractors import (  # noqa: E402
    extract_claims,
    extract_facts_used,
    extract_questions,
)
from eval.benchmark_support import audio_path, validate_inputs  # noqa: E402
from eval.model_config import configure_eval_model, permanent_provider_error  # noqa: E402

_SCHEMAS = REPO_ROOT / "dataset" / "BTC-Data-Vong1-TEAMS" / "schemas"
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


def _replace_order_ids(value, order_id_map: dict[str, str]):
    """Normalize opaque runtime IDs to scenario IDs in evaluation traces only."""
    if isinstance(value, dict):
        return {
            key: _replace_order_ids(item, order_id_map)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_order_ids(item, order_id_map) for item in value]
    if isinstance(value, str):
        normalized = value
        for runtime_id, scenario_id in order_id_map.items():
            normalized = normalized.replace(runtime_id, scenario_id)
        return normalized
    return value


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
) -> list[dict]:
    rows = []
    scenario_id = scenario["scenario_id"]
    customer_phone = scenario.get("customer_phone")
    calls_spec: dict = scenario.get("calls", {})
    expected_order_id = next(
        (
            spec.get("facts_established", {}).get("order_id")
            for spec in calls_spec.values()
            if spec.get("facts_established", {}).get("order_id")
        ),
        None,
    )
    order_id_map: dict[str, str] = {}
    created_order_ids: set[str] = set()

    def cleanup_created_orders() -> None:
        if not cleanup_orders or not created_order_ids:
            return
        try:
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
    if config == "full":
        seed_history = [
            episode
            for call_spec in calls_spec.values()
            for episode in call_spec.get("seed_history", [])
        ]
        if seed_history:
            customer = db_client.get_customer(phone=customer_phone)
            customer_id = customer.get("customer_id") if customer.get("found") else None
            if customer_id:
                for episode in seed_history:
                    summary = (
                        f"Channel: {episode.get('channel', 'unknown')}\n"
                        f"Outcome: {episode.get('outcome', 'unknown')}\n"
                        f"Summary: {episode.get('summary', '')}"
                    )
                    harness.memory.record_episode(
                        customer_id,
                        summary,
                        occurred_on=episode.get("date"),
                        source_id=episode.get("session_id"),
                    )
    previous_call_date = date(2026, 10, 15)

    for call_key in sorted(calls_spec.keys()):  # call_1, call_2, ...
        spec = calls_spec[call_key]
        input_mode = spec.get("input_mode", "clean")
        customer_turns: list[str] = (
            spec.get("customer_turns_asr")
            if spec.get("customer_turns_asr")
            else spec.get("customer_turns", [])
        )
        if spec.get("call_date"):
            current_call_date = date.fromisoformat(spec["call_date"])
        elif call_key == "call_1":
            current_call_date = date(2026, 10, 15)
        else:
            current_call_date = previous_call_date + timedelta(
                days=int(spec.get("days_later", 0))
            )
        previous_call_date = current_call_date
        call_date = current_call_date.isoformat()
        conversation_id = f"{run_id}__{scenario_id}__{call_key}"
        conv_state = ConversationState(conversation_id=conversation_id)

        for turn_idx, customer_text in enumerate(customer_turns, start=1):
            if sleep_turn > 0 and (turn_idx > 1 or call_key != "call_1"):
                await asyncio.sleep(sleep_turn)
            t0 = time.perf_counter()
            try:
                audio_file = None
                audio_info = None
                if input_kind == "audio":
                    if audio_root is None:
                        raise ValueError("audio_root is required for audio evaluation")
                    audio_file = audio_path(audio_root, scenario_id, call_key, turn_idx)
                    with wave.open(str(audio_file), "rb") as wav:
                        audio_info = {"path":str(audio_file), "duration_seconds":wav.getnframes()/wav.getframerate()}
                turn_input = TurnInput(
                    conversation_id=conversation_id,
                    text=None if audio_file else customer_text,
                    audio=audio_file.read_bytes() if audio_file else None,
                    channel=Channel.CHAT,
                    customer_hint=customer_phone,
                    metadata={
                        "call_date": call_date,
                        "call_key": call_key,
                        "scenario_id": scenario_id,
                    },
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
                if expected_order_id and expected_order_id not in order_id_map.values():
                    created_id = next(
                        (
                            call.get("result", {}).get("order_id")
                            for call in tool_calls
                            if call.get("name") == "order.create"
                            and isinstance(call.get("result"), dict)
                            and call["result"].get("order_id")
                        ),
                        None,
                    )
                    if created_id:
                        order_id_map[str(created_id)] = str(expected_order_id)
                tool_calls = _replace_order_ids(tool_calls, order_id_map)
                is_baseline = config == "baseline_no_memory"
                response_text = _replace_order_ids(
                    result.response_text or "", order_id_map
                )
                trace_memory_writes = _replace_order_ids(
                    result.memory_writes, order_id_map
                )
                row = {
                    "run_id": run_id,
                    "config": config,
                    "scenario_id": scenario_id,
                    "call": call_key,
                    "turn": turn_idx,
                    "customer_text": turn_input.metadata.get("raw_asr_transcript", customer_text),
                    "reference_customer_text": spec.get("customer_turns", customer_turns)[turn_idx - 1],
                    "normalized_customer_text": turn_input.text,
                    "agent_text": response_text,
                    "questions": extract_questions(response_text),
                    "facts_used": (
                        []
                        if is_baseline or call_key == "call_1"
                        else extract_facts_used(
                            response_text, tool_calls, result.call_brief
                        )
                    ),
                    "claims": extract_claims(
                        tool_calls,
                        call_date=call_date,
                        response_text=response_text,
                    ),
                    "tool_calls": tool_calls,
                    "memory_writes": [] if is_baseline else trace_memory_writes,
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
                    "customer_text": customer_text,
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
            _TRACE_VALIDATOR.validate(row)
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
async def main():
    parser = argparse.ArgumentParser(
        description="Chạy AI Agent thật qua BTC scenarios và ghi trace JSONL."
    )
    parser.add_argument(
        "--scenarios",
        default=str(DEFAULT_SCENARIOS_DIR),
        help=f"Thư mục chứa các scenario JSON (default: {DEFAULT_SCENARIOS_DIR})",
    )
    parser.add_argument(
        "--config",
        default="full",
        choices=["full", "baseline_no_memory"],
        help="Config name ghi vào trace (default: full)",
    )
    parser.add_argument("--run-id", default="team_run", dest="run_id",
                        help="Tên định danh của run (default: team_run)")
    parser.add_argument("--out", default=None,
                        help="Đường dẫn JSONL output (default: outputs/eval/<run_id>.jsonl)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Chỉ chạy N scenario đầu (để test nhanh)")
    parser.add_argument("--scenario-id", default=None, dest="scenario_id",
                        help="Chỉ chạy một scenario cụ thể, vd: SC-001")
    parser.add_argument("--input-kind", choices=["text","audio"], default="text")
    parser.add_argument("--llm-provider",default=None)
    parser.add_argument("--llm-model",default=None)
    parser.add_argument("--audio-root", type=Path, default=REPO_ROOT / "dataset/iterative-refinement/audio")
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
    args = parser.parse_args()
    configure_eval_model(args.llm_provider,args.llm_model)

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than zero")
    if args.max_turns is not None and args.max_turns <= 0:
        parser.error("--max-turns must be greater than zero")
    if args.max_retries <= 0:
        parser.error("--max-retries must be greater than zero")
    if args.sleep < 0 or args.sleep_scenario < 0:
        parser.error("--sleep and --sleep-scenario cannot be negative")

    scenarios_dir = Path(args.scenarios)
    DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"{args.run_id}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Thu thập file
    all_files = sorted(
        path for path in scenarios_dir.glob("*.json") if not path.name.startswith("_")
    )
    if not all_files:
        print(f"[ERROR] Không tìm thấy file JSON trong: {scenarios_dir}", file=sys.stderr)
        sys.exit(1)

    if args.scenario_ids:
        file_map = {path.stem: path for path in all_files}
        missing = [sid for sid in args.scenario_ids if sid not in file_map]
        if missing:
            print(f"[ERROR] Không tìm thấy các scenario: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        all_files = [file_map[sid] for sid in args.scenario_ids]
    elif args.scenario_id:
        all_files = [path for path in all_files if path.stem == args.scenario_id]
        if not all_files:
            print(f"[ERROR] Không tìm thấy: {args.scenario_id}", file=sys.stderr)
            sys.exit(1)

    if args.limit is not None:
        all_files = all_files[:args.limit]
    selected = {p.stem:json.loads(p.read_text(encoding="utf-8")) for p in all_files}
    validate_inputs(selected, args.audio_root if args.input_kind == "audio" else None)

    print(f"[Runner] Config         : {args.config}")
    print(f"[Runner] Run ID         : {args.run_id}")
    print(f"[Runner] Scenarios      : {len(all_files)} files")
    print(f"[Runner] Sleep turn     : {args.sleep}s | Sleep scenario: {args.sleep_scenario}s")
    print(f"[Runner] Persist memory : {args.persist_memory}")
    print(f"[Runner] Cleanup orders : {args.cleanup_orders}")
    print(f"[Runner] Output         : {out_path}")
    print()

    print("[Runner] Khởi động Agent Harness...")
    memory_mode = (
        ("durable" if args.persist_memory else "evaluation")
        if args.config == "full"
        else "disabled"
    )
    harness = await build_deepagent_harness_async(memory_mode=memory_mode)
    print("[Runner] Agent sẵn sàng.\n")

    total_rows = 0
    failures = 0
    try:
        with out_path.open("w", encoding="utf-8") as out_f:
            for i, fpath in enumerate(all_files, start=1):
                if i > 1 and args.sleep_scenario > 0:
                    await asyncio.sleep(args.sleep_scenario)
                with open(fpath, encoding="utf-8") as scenario_file:
                    scenario = json.load(scenario_file)
                sid = scenario.get("scenario_id", fpath.stem)
                print(f"[{i:3d}/{len(all_files)}] {sid} starting...", flush=True)

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
                    )
                    elapsed = time.perf_counter() - t0
                    print(f"[{i:3d}/{len(all_files)}] {sid}: ✓ {len(rows)} turns, {elapsed:.1f}s", flush=True)
                    for row in rows:
                        row["latency_warmup"] = total_rows < 3
                        total_rows += 1
                        failures += int("_error" in row)
                        out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        out_f.flush()
                    if any(row.get("_fatal_provider_error") for row in rows):
                        print("[Runner] Stopping: provider billing/auth/model access needs attention.",flush=True)
                        break
                except Exception as scenario_exc:
                    failures += 1
                    elapsed = time.perf_counter() - t0
                    print(f"[{i:3d}/{len(all_files)}] {sid}: FAILED ({elapsed:.1f}s) - {scenario_exc}", flush=True)
    finally:
        await harness.__aexit__(None, None, None)

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
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
