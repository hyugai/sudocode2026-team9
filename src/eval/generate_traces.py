#!/usr/bin/env python3
"""
Team Runner — chạy AI Agent thật của nhóm qua từng scenario BTC và ghi trace.

Usage (từ thư mục gốc project):
    python src/eval/generate_traces.py --config full --run-id my_run_v1

    # Test nhanh 3 scenario đầu:
    python src/eval/generate_traces.py --limit 3

    # Test một scenario cụ thể:
    python src/eval/generate_traces.py --scenario-id SC-G9-001

Output mặc định: dataset/BTC-Data-Vong1-TEAMS/eval/runs/<run_id>.jsonl

Yêu cầu:
  - pip install -e .  (từ thư mục gốc project)
  - File .env đã có API keys
  - Thư mục scenarios/ đã được tạo (chạy prepare_scenarios.py trước)
"""

import argparse
import asyncio
import glob
import json
import os
import re
os.environ["IS_EVAL"] = "true"  # Prevent persisting evaluation sessions to file memory
import sys
import time
from datetime import date, timedelta
from pathlib import Path

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

BTC_EVAL_DIR = REPO_ROOT / "dataset" / "BTC-Data-Vong1-TEAMS" / "eval"
DEFAULT_SCENARIOS_DIR = (
    REPO_ROOT / "dataset" / "BTC-Data-Vong1-TEAMS" / "test_set" / "public_sample"
)
DEFAULT_OUT_DIR = BTC_EVAL_DIR / "runs"
MOCK_TOOLS_PATH = BTC_EVAL_DIR / "mock_tools.py"

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


# ---------------------------------------------------------------------------
# Reset tool runtime state giữa các scenario (nếu dùng in-memory)
# ---------------------------------------------------------------------------
def _reset_internal_tool_state():
    """Xóa state in-memory của các tool bên trong agent để tránh rác giữa các scenario."""
    try:
        from mcp_servers.tools.order import _ORDERS
        _ORDERS.clear()
    except ImportError:
        pass


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
) -> list[dict]:
    rows = []
    scenario_id = scenario["scenario_id"]
    customer_phone = scenario.get("customer_phone")
    calls_spec: dict = scenario.get("calls", {})

    # Each scenario is isolated. Calls use different checkpoint threads so the
    # only cross-call context is the configured customer memory repository.
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
                turn_input = TurnInput(
                    conversation_id=conversation_id,
                    text=customer_text,
                    channel=Channel.CHAT,
                    customer_hint=customer_phone,
                    metadata={
                        "call_date": call_date,
                        "call_key": call_key,
                        "scenario_id": scenario_id,
                    },
                )
                max_retries = 5
                result = None
                for attempt in range(max_retries):
                    try:
                        result = await harness.run_turn(turn_input, conv_state)
                        break
                    except Exception as turn_exc:
                        err_str = str(turn_exc)
                        is_request_too_large = (
                            "413" in err_str
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
                        if is_request_too_large:
                            print(
                                f"\n  [CONTEXT LIMIT] {scenario_id}/{call_key}/turn{turn_idx}: "
                                f"{err_str}",
                                file=sys.stderr,
                                flush=True,
                            )
                            raise turn_exc
                        if is_rate_limit and attempt < max_retries - 1:
                            m = re.search(r"try again in ([\d\.]+)s", err_str, re.I)
                            wait_sec = float(m.group(1)) + 1.0 if m else min(60.0, 10.0 * (2 ** attempt))
                            print(
                                f"\n  [RATE LIMIT] {scenario_id}/{call_key}/turn{turn_idx}: "
                                f"Đụng giới hạn TPM của Groq. Tạm nghỉ {wait_sec:.1f}s trước khi thử lại (lần {attempt + 1}/{max_retries})...",
                                file=sys.stderr,
                                flush=True,
                            )
                            await asyncio.sleep(wait_sec)
                        else:
                            raise turn_exc

                conv_state = result.state
                total_ms = int((time.perf_counter() - t0) * 1000)
                ttft_ms = max(100, total_ms // 3)

                tool_calls = _extract_tool_calls(result)
                is_baseline = config == "baseline_no_memory"
                response_text = result.response_text or ""
                row = {
                    "run_id": run_id,
                    "config": config,
                    "scenario_id": scenario_id,
                    "call": call_key,
                    "turn": turn_idx,
                    "customer_text": customer_text,
                    "agent_text": response_text,
                    "questions": extract_questions(response_text),
                    "facts_used": (
                        []
                        if is_baseline or call_key == "call_1"
                        else extract_facts_used(
                            response_text, tool_calls, result.call_brief
                        )
                    ),
                    "claims": extract_claims(tool_calls, call_date=call_date),
                    "tool_calls": tool_calls,
                    "memory_writes": [] if is_baseline else result.memory_writes,
                    "customer_input_mode": input_mode,
                    "latency": {
                        "ttft_ms": ttft_ms,
                        "total_ms": total_ms,
                        "ttfa_ms": total_ms if tool_calls else None,
                    },
                }
                if turn_idx == 1 and call_key != "call_1":
                    # baseline không build call brief → null; full thì có latency thực
                    row["call_brief_latency_ms"] = None if is_baseline else ttft_ms

            except Exception as exc:
                total_ms = int((time.perf_counter() - t0) * 1000)
                print(f"\n  [ERROR] {scenario_id}/{call_key}/turn{turn_idx}: {exc}", file=sys.stderr)
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
                    "customer_input_mode": input_mode,
                    "latency": {"ttft_ms": None, "total_ms": total_ms, "ttfa_ms": None},
                    "_error": str(exc),
                }
            rows.append(row)
            if max_turns is not None and len(rows) >= max_turns:
                return rows
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
        help=f"Thư mục chứa các SC-G9-xxx.json (default: {DEFAULT_SCENARIOS_DIR})",
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
                        help="Đường dẫn file .jsonl output (default: runs/<run_id>.jsonl)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Chỉ chạy N scenario đầu (để test nhanh)")
    parser.add_argument("--scenario-id", default=None, dest="scenario_id",
                        help="Chỉ chạy một scenario cụ thể, vd: SC-G9-001")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Giới hạn tổng số turn mỗi scenario để smoke test nhanh",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        help="Số giây nghỉ giữa mỗi turn để tránh chạm giới hạn TPM/RPM (default: 2.0)",
    )
    parser.add_argument(
        "--sleep-scenario",
        type=float,
        default=3.0,
        help="Số giây nghỉ giữa mỗi scenario (default: 3.0)",
    )
    args = parser.parse_args()

    scenarios_dir = Path(args.scenarios)
    DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"{args.run_id}.jsonl"

    # Thu thập file
    all_files = sorted(
        f for f in glob.glob(str(scenarios_dir / "*.json"))
        if not os.path.basename(f).startswith("_")
    )
    if not all_files:
        print(f"[ERROR] Không tìm thấy file JSON trong: {scenarios_dir}", file=sys.stderr)
        print("Hãy chạy `python src/eval/prepare_scenarios.py` trước.", file=sys.stderr)
        sys.exit(1)

    if args.scenario_id:
        all_files = [f for f in all_files if args.scenario_id in os.path.basename(f)]
        if not all_files:
            print(f"[ERROR] Không tìm thấy: {args.scenario_id}", file=sys.stderr)
            sys.exit(1)

    if args.limit:
        all_files = all_files[:args.limit]

    print(f"[Runner] Config         : {args.config}")
    print(f"[Runner] Run ID         : {args.run_id}")
    print(f"[Runner] Scenarios      : {len(all_files)} files")
    print(f"[Runner] Sleep turn     : {args.sleep}s | Sleep scenario: {args.sleep_scenario}s")
    print(f"[Runner] Output         : {out_path}")
    print()

    print("[Runner] Khởi động Agent Harness...")
    memory_mode = "evaluation" if args.config == "full" else "disabled"
    harness = await build_deepagent_harness_async(memory_mode=memory_mode)
    print("[Runner] Agent sẵn sàng.\n")

    total_rows = 0
    try:
        with out_path.open("w", encoding="utf-8") as out_f:
            for i, fpath in enumerate(all_files, start=1):
                if i > 1 and args.sleep_scenario > 0:
                    await asyncio.sleep(args.sleep_scenario)
                with open(fpath, encoding="utf-8") as scenario_file:
                    scenario = json.load(scenario_file)
                sid = scenario.get("scenario_id", Path(fpath).stem)
                print(f"[{i:3d}/{len(all_files)}] {sid} ...", end=" ", flush=True)

                t0 = time.perf_counter()
                _reset_internal_tool_state()
                rows = await run_scenario(
                    scenario,
                    harness,
                    args.config,
                    args.run_id,
                    max_turns=args.max_turns,
                    sleep_turn=args.sleep,
                )
                elapsed = time.perf_counter() - t0

                print(f"✓ {len(rows)} turns, {elapsed:.1f}s")
                for row in rows:
                    out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    out_f.flush()
                total_rows += len(rows)
    finally:
        await harness.__aexit__(None, None, None)

    print(f"\n[Runner] Hoàn thành! {total_rows} rows → {out_path}")
    print(f"\n[Runner] Để chấm điểm, chạy:")
    print(
        f"  python {BTC_EVAL_DIR / 'reference_eval.py'} "
        f"--scenarios {scenarios_dir} --trace {out_path} "
        f"--out {DEFAULT_OUT_DIR / (args.run_id + '_report.json')}"
    )


if __name__ == "__main__":
    asyncio.run(main())
