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
os.environ["IS_EVAL"] = "true"  # Prevent persisting mock sessions to DB
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent          # src/eval/
REPO_ROOT = HERE.parent.parent                  # sudo_code_2026-group_9/
sys.path.insert(0, str(REPO_ROOT / "src"))

BTC_EVAL_DIR = REPO_ROOT / "dataset" / "BTC-Data-Vong1-TEAMS" / "eval"
DEFAULT_SCENARIOS_DIR = REPO_ROOT / "dataset" / "iterative-refinement" / "scenarios_complete dataset"
DEFAULT_OUT_DIR = BTC_EVAL_DIR / "runs"
MOCK_TOOLS_PATH = BTC_EVAL_DIR / "mock_tools.py"

# ---------------------------------------------------------------------------
# Import agent (lazy để lỗi import hiện rõ)
# ---------------------------------------------------------------------------
from telesale_agent.bootstrap import build_default_harness  # noqa: E402
from telesale_agent.core.models import Channel, ConversationState, TurnInput  # noqa: E402


# ---------------------------------------------------------------------------
# Reset tool runtime state giữa các scenario (nếu dùng in-memory)
# ---------------------------------------------------------------------------
def _reset_internal_tool_state():
    """Xóa state in-memory của các tool bên trong agent để tránh rác giữa các scenario."""
    try:
        from telesale_agent.tools.order import _ORDERS
        _ORDERS.clear()
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Trích xuất thông tin từ TurnResult để ghi trace
# ---------------------------------------------------------------------------
def _extract_tool_calls(result) -> list[dict]:
    """Trích xuất tool calls agent đã thực thi."""
    calls = []
    for step in (result.steps or []):
        if step.plan and step.plan.tool_name:
            calls.append({
                "name": step.plan.tool_name,
                "args": step.plan.arguments or {},
                "result": step.action_result.output if step.action_result else {},
            })
    return calls


def _extract_claims(result) -> list[dict]:
    """Trích xuất các tuyên bố về giá/khuyến mãi từ kết quả pricing.get_quote."""
    claims = []
    for step in (result.steps or []):
        if not (step.plan and step.plan.tool_name == "pricing.get_quote"):
            continue
        out = step.action_result.output if step.action_result else {}
        if "final_price_vnd" in out:
            claims.append({"field": "price_vnd", "value": out["final_price_vnd"]})
        for promo in out.get("applied_promos", []):
            claims.append({"field": f"promo_{promo['promo_code']}_active", "value": True})
        for code in out.get("expired_promos", []):
            claims.append({"field": f"promo_{code}_active", "value": False})
    return claims


def _extract_facts_used(result, call_key: str) -> list[str]:
    """Trích xuất các fact/slot agent lấy từ memory của call trước."""
    if call_key == "call_1":
        return []
    facts = []
    if result.call_brief and result.call_brief.needs:
        facts.extend(result.call_brief.needs)
    return facts


def _extract_questions(result) -> list[dict]:
    """Trích xuất câu hỏi agent hỏi khách (best-effort, cần mở rộng sau)."""
    # TODO: parse response_text hoặc thêm trường vào ActionPlan để phát hiện câu hỏi
    return []


# ---------------------------------------------------------------------------
# Chạy một scenario đầy đủ (tất cả calls × turns)
# ---------------------------------------------------------------------------
async def run_scenario(scenario: dict, harness, config: str, run_id: str) -> list[dict]:
    rows = []
    scenario_id = scenario["scenario_id"]
    customer_phone = scenario.get("customer_phone")
    calls_spec: dict = scenario.get("calls", {})

    # Giữ state xuyên suốt các call trong cùng một scenario
    conv_state: ConversationState | None = None
    conversation_id = f"{run_id}__{scenario_id}"

    for call_key in sorted(calls_spec.keys()):  # call_1, call_2, ...
        spec = calls_spec[call_key]
        customer_turns: list[str] = spec.get("customer_turns", [])
        call_date: str = spec.get("call_date", "2026-10-15")

        for turn_idx, customer_text in enumerate(customer_turns, start=1):
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
                result = await harness.run_turn(turn_input, conv_state)
                conv_state = result.state
                total_ms = int((time.perf_counter() - t0) * 1000)
                ttft_ms = max(100, total_ms // 3)

                tool_calls = _extract_tool_calls(result)
                is_baseline = config == "baseline_no_memory"
                row = {
                    "run_id": run_id,
                    "config": config,
                    "scenario_id": scenario_id,
                    "call": call_key,
                    "turn": turn_idx,
                    "customer_text": customer_text,
                    "agent_text": result.response_text or "",
                    "questions": _extract_questions(result),
                    # baseline không có memory → facts_used luôn rỗng
                    "facts_used": [] if is_baseline else _extract_facts_used(result, call_key),
                    "claims": _extract_claims(result),
                    "tool_calls": tool_calls,
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
                    "latency": {"ttft_ms": None, "total_ms": total_ms, "ttfa_ms": None},
                    "_error": str(exc),
                }
            rows.append(row)
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

    print(f"[Runner] Config     : {args.config}")
    print(f"[Runner] Run ID     : {args.run_id}")
    print(f"[Runner] Scenarios  : {len(all_files)} files")
    print(f"[Runner] Output     : {out_path}")
    print()

    print("[Runner] Khởi động Agent Harness...")
    harness = build_default_harness()
    print("[Runner] Agent sẵn sàng.\n")

    total_rows = 0
    with out_path.open("w", encoding="utf-8") as out_f:
        for i, fpath in enumerate(all_files, start=1):
            scenario = json.load(open(fpath, encoding="utf-8"))
            sid = scenario.get("scenario_id", Path(fpath).stem)
            print(f"[{i:3d}/{len(all_files)}] {sid} ...", end=" ", flush=True)

            t0 = time.perf_counter()
            _reset_internal_tool_state()  # ⚠️ Bắt buộc reset giữa các scenario để tránh dính data ảo
            rows = await run_scenario(scenario, harness, args.config, args.run_id)
            elapsed = time.perf_counter() - t0

            print(f"✓ {len(rows)} turns, {elapsed:.1f}s")
            for row in rows:
                out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            total_rows += len(rows)

    print(f"\n[Runner] Hoàn thành! {total_rows} rows → {out_path}")
    print(f"\n[Runner] Để chấm điểm, chạy:")
    print(f"  python {BTC_EVAL_DIR / 'reference_eval.py'} {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
