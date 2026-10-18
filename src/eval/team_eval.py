#!/usr/bin/env python3
"""Team evaluator built on top of the immutable BTC reference evaluator.

The reference evaluator remains the source of truth for BTC metrics. This
module adds team-owned operational metrics without changing that file.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval.benchmark_support import measured_latency, trace_health, compare_metrics


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
REFERENCE_EVAL = (
    REPO_ROOT / "dataset" / "BTC-Data-Vong1-TEAMS" / "eval" / "reference_eval.py"
)
DEFAULT_RAG_QA = (
    REPO_ROOT / "dataset" / "BTC-Data-Vong1-TEAMS" / "rag" / "qa_labeled.json"
)
MUTATION_TOOLS = {
    "order.create",
    "order.update",
    "schedule.callback",
    "handoff.transfer",
}


def _load_reference() -> ModuleType:
    spec = importlib.util.spec_from_file_location("btc_reference_eval", REFERENCE_EVAL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load reference evaluator: {REFERENCE_EVAL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REFERENCE = _load_reference()


def _pct(numerator: int, denominator: int) -> float | None:
    return round(100.0 * numerator / denominator, 1) if denominator else None


def tool_call_accuracy(
    scenarios: dict[str, Any], trace: dict[tuple[str, str], list[dict[str, Any]]]
) -> dict[str, Any]:
    """Score required business calls by tool name and required arguments.

    Retrieval/read calls are intentionally ignored unless a scenario explicitly
    requires them. Missing expected calls, forbidden mutations and unexpected
    mutations remain in the evaluated denominator.
    """
    expected = name_hits = exact = missing = wrong_args = 0
    forbidden = unexpected_mutations = 0
    examples: list[dict[str, Any]] = []

    for scenario_id, scenario in scenarios.items():
        for call_key, call_spec in scenario["calls"].items():
            rows = trace.get((scenario_id, call_key), [])
            actual_calls = [
                tool_call
                for row in rows
                for tool_call in row.get("tool_calls", [])
            ]
            success_if = call_spec.get("success_if") or {}
            expected_specs: list[tuple[str, dict[str, Any]]] = []
            primary = success_if.get("tool_called")
            if primary:
                expected_specs.append((primary, success_if.get("args_match") or {}))
                expected_specs.extend(
                    ("order.create", {"sku": sku})
                    for sku in success_if.get("also_ordered", [])
                )

            for tool_name, expected_args in expected_specs:
                expected += 1
                same_name = [
                    call for call in actual_calls if call.get("name") == tool_name
                ]
                name_hits += int(bool(same_name))
                matches = [
                    call
                    for call in same_name
                    if REFERENCE.args_match(expected_args, call.get("args", {}))
                ]
                if tool_name == "handoff.transfer" and success_if.get(
                    "brief_must_contain"
                ):
                    required = success_if["brief_must_contain"]
                    matches = [
                        call
                        for call in same_name
                        if all(
                            (call.get("args", {}).get("brief") or {}).get(key)
                            not in (None, "", [])
                            for key in required
                        )
                    ]
                if matches:
                    exact += 1
                elif same_name:
                    wrong_args += 1
                    examples.append(
                        {
                            "scenario": scenario_id,
                            "call": call_key,
                            "type": "wrong_args",
                            "expected_tool": tool_name,
                            "expected_args": expected_args,
                            "actual_args": [
                                call.get("args", {}) for call in same_name
                            ],
                        }
                    )
                else:
                    missing += 1
                    examples.append(
                        {
                            "scenario": scenario_id,
                            "call": call_key,
                            "type": "missing_tool",
                            "expected_tool": tool_name,
                            "expected_args": expected_args,
                        }
                    )

            forbidden_names = set(success_if.get("must_not_call_tools", []))
            forbidden_calls = [
                call
                for call in actual_calls
                if call.get("name") in forbidden_names
            ]
            forbidden += len(forbidden_calls)
            expected_names = {name for name, _ in expected_specs}
            unexpected = [
                call
                for call in actual_calls
                if call.get("name") in MUTATION_TOOLS
                and call.get("name") not in expected_names
                and call.get("name") not in forbidden_names
            ]
            unexpected_mutations += len(unexpected)
            examples.extend(
                {
                    "scenario": scenario_id,
                    "call": call_key,
                    "type": "forbidden_tool",
                    "actual_tool": call.get("name"),
                    "actual_args": call.get("args", {}),
                }
                for call in forbidden_calls
            )
            examples.extend(
                {
                    "scenario": scenario_id,
                    "call": call_key,
                    "type": "unexpected_mutation",
                    "actual_tool": call.get("name"),
                    "actual_args": call.get("args", {}),
                }
                for call in unexpected
            )

    evaluated = expected + forbidden + unexpected_mutations
    return {
        "value": _pct(exact, evaluated),
        "correct_calls": exact,
        "total_evaluated_calls": evaluated,
        "expected_call_recall": _pct(exact, expected),
        "tool_name_accuracy": _pct(name_hits, expected),
        "expected_calls": expected,
        "missing_calls": missing,
        "wrong_argument_calls": wrong_args,
        "forbidden_calls": forbidden,
        "unexpected_mutation_calls": unexpected_mutations,
        "examples": examples[:40],
        "policy": (
            "Exact expected tool+required args are correct; missing expected, "
            "forbidden and unexpected mutation calls count against accuracy."
        ),
    }


def estimated_cost_per_call(
    trace: dict[tuple[str, str], list[dict[str, Any]]],
    pricing: dict[str, float | None],
) -> dict[str, Any]:
    """Estimate cost from provider usage plus configurable operation rates."""
    configured = any(value is not None for value in pricing.values())
    rates = {key: float(value or 0.0) for key, value in pricing.items()}
    by_call: list[dict[str, Any]] = []
    usage_rows = 0
    total_rows = 0

    for (scenario_id, call_key), rows in sorted(trace.items()):
        total_rows += len(rows)
        usage_rows += sum("usage" in row for row in rows)
        input_tokens = sum(
            int((row.get("usage") or {}).get("input_tokens", 0)) for row in rows
        )
        output_tokens = sum(
            int((row.get("usage") or {}).get("output_tokens", 0)) for row in rows
        )
        requests = sum(
            int((row.get("usage") or {}).get("requests", 0)) for row in rows
        )
        failed_requests = sum(
            int((row.get("usage") or {}).get("failed_requests", 0))
            for row in rows
        )
        tool_calls = sum(len(row.get("tool_calls", [])) for row in rows)
        memory_writes = sum(len(row.get("memory_writes", [])) for row in rows)
        memory_bytes = sum(
            len(
                json.dumps(row.get("memory_writes", []), ensure_ascii=False).encode(
                    "utf-8"
                )
            )
            for row in rows
        )
        total_cost = (
            input_tokens / 1_000_000 * rates.get("input_per_million", 0.0)
            + output_tokens / 1_000_000 * rates.get("output_per_million", 0.0)
            + tool_calls * rates.get("tool_call", 0.0)
            + memory_writes * rates.get("memory_write", 0.0)
            + memory_bytes / (1024 * 1024) * rates.get("storage_per_mb", 0.0)
            + rates.get("fixed_call", 0.0)
        )
        by_call.append(
            {
                "scenario": scenario_id,
                "call": call_key,
                "llm_requests": requests,
                "failed_llm_requests": failed_requests,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "tool_calls": tool_calls,
                "memory_writes": memory_writes,
                "memory_bytes_observed": memory_bytes,
                "estimated_cost_usd": round(total_cost, 8) if configured else None,
            }
        )

    costs = [
        item["estimated_cost_usd"]
        for item in by_call
        if item["estimated_cost_usd"] is not None
    ]
    return {
        "configured": configured,
        "usage_trace_coverage": _pct(usage_rows, total_rows),
        "average_per_call_usd": round(statistics.mean(costs), 8)
        if costs
        else None,
        "total_usd": round(sum(costs), 8) if costs else None,
        "n_calls": len(by_call),
        "pricing": pricing,
        "by_call": by_call,
        "note": (
            "Storage covers serialized memory_writes present in the trace. "
            "Database, hosting and network costs need rates supplied by the team."
        ),
    }


def rag_recall(qa_path: Path, results_path: Path) -> dict[str, Any]:
    """Compute document recall@k (micro and macro), hit rate and abstention."""
    questions = json.loads(qa_path.read_text(encoding="utf-8"))["questions"]
    results = json.loads(results_path.read_text(encoding="utf-8"))
    output: dict[str, Any] = {}
    for k in (3, 5):
        found_total = relevant_total = hits = n = multi_full = multi_n = 0
        per_question: list[float] = []
        for question in questions:
            relevant = set(question.get("relevant_chunk_ids", []))
            result = results.get(question["qid"])
            if not relevant:
                continue
            result = result or {}
            retrieved = {
                chunk.split("#")[0]
                for chunk in result.get("retrieved_chunk_ids", [])[:k]
            }
            found = len(relevant & retrieved)
            found_total += found
            relevant_total += len(relevant)
            hits += int(found > 0)
            n += 1
            per_question.append(found / len(relevant))
            if question.get("type") == "multi_hop":
                multi_n += 1
                multi_full += int(relevant <= retrieved)
        output[f"recall@{k}"] = _pct(found_total, relevant_total)
        output[f"macro_recall@{k}"] = (
            round(statistics.mean(per_question) * 100, 1)
            if per_question
            else None
        )
        output[f"hit_rate@{k}"] = _pct(hits, n)
        output[f"multi_hop_full_recall@{k}"] = _pct(multi_full, multi_n)

    for question_type in ("unanswerable", "restricted"):
        selected = [q for q in questions if q.get("type") == question_type]
        abstained = sum(
            1
            for question in selected
            if results.get(question["qid"], {}).get("abstained")
        )
        output[f"abstain_rate_{question_type}"] = _pct(
            abstained, len(selected)
        )
    answerable = [
        q
        for q in questions
        if q.get("type") not in ("unanswerable", "restricted")
    ]
    output["false_abstain_rate"] = _pct(
        sum(
            1
            for question in answerable
            if results.get(question["qid"], {}).get("abstained")
        ),
        len(answerable),
    )
    return output


def _memory_write_quality(path: str | None) -> dict[str, Any]:
    if not path:
        return {
            "status": "not_run",
            "reason": "Pass --memory-judge-report after running the optional LLM judge.",
        }
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    return report


def _pricing(args: argparse.Namespace) -> dict[str, float | None]:
    return {
        "input_per_million": args.input_usd_per_million,
        "output_per_million": args.output_usd_per_million,
        "tool_call": args.tool_call_usd,
        "memory_write": args.memory_write_usd,
        "storage_per_mb": args.memory_storage_usd_per_mb,
        "fixed_call": args.fixed_call_usd,
    }


def evaluate_team(
    scenarios: dict[str, Any],
    trace: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    pricing: dict[str, float | None],
    memory_judge_report: str | None = None,
    warmup_turns: int = 3,
) -> dict[str, Any]:
    result = REFERENCE.evaluate(scenarios, trace)
    result["trace_health"] = trace_health(scenarios, trace)
    result["latency"] = measured_latency(trace, REFERENCE, warmup_turns)
    # Preserve the official score for exact reproduction; enforce actual
    # execution and nonempty calls in the team's task-success score.
    result["reference_task_success_rate"] = deepcopy(result["task_success_rate"])
    execution_trace = {}
    for key, rows in trace.items():
        execution_trace[key] = [{**row, "tool_calls":[tc for tc in row.get("tool_calls",[])
                                    if tool_execution_succeeded(tc)]} for row in rows]
    tsr = deepcopy(result["task_success_rate"])
    passed = 0
    failures = []
    total = 0
    hard_total = hard_passed = 0
    for sid, scenario in scenarios.items():
        checks = []
        for call, spec in scenario["calls"].items():
            if not spec.get("success_if"):
                continue
            rows = trace.get((sid,call),[])
            ok, reasons = REFERENCE.check_call(spec, rows)
            if not rows or any(r.get("_error") for r in rows):
                ok = False
                reasons.append("missing/failed customer turn")
            tool = spec["success_if"].get("tool_called")
            if ok and tool in MUTATION_TOOLS:
                ok, extra = REFERENCE.check_call(spec, execution_trace.get((sid,call),[]))
                reasons.extend(extra)
            checks.append(bool(ok))
            if not ok:
                failures.append({"scenario":sid,"call":call,"reasons":reasons})
        if checks:
            total += 1
            passed += int(all(checks))
            if scenario.get("hard_case"):
                hard_total += 1
                hard_passed += int(all(checks))
    tsr.update(value=_pct(passed,total),passed=passed,total=total,failures=failures[:40],
               hard_cases={"value":_pct(hard_passed,hard_total),"total":hard_total} if hard_total else None,
               policy="BTC success conditions plus nonempty calls and successful mutation results")
    result["task_success_rate"] = tsr
    result["calls_to_close"] = REFERENCE.calls_to_close(scenarios,execution_trace)
    price_scenarios = deepcopy(scenarios)
    for scenario in price_scenarios.values():
        for spec in scenario["calls"].values():
            spec["ground_truth_facts"] = {k:v for k,v in spec.get("ground_truth_facts",{}).items()
                                           if k.startswith(("price", "list_price"))}
    result["hallucination_rate"]["price_only"] = REFERENCE.hallucination_rate(price_scenarios,trace)
    result["tool_call_accuracy"] = tool_call_accuracy(scenarios, trace)
    result["estimated_cost_per_call"] = estimated_cost_per_call(trace, pricing)
    result["memory_write_quality"] = _memory_write_quality(memory_judge_report)
    result["calls_to_close"] = {
        **result["calls_to_close"],
        "measurement_mode": "scripted_customer",
        "note": (
            "Current benchmark replays dataset customer_turns; it is not a "
            "dynamic customer-agent simulation."
        ),
    }
    return result


def tool_execution_succeeded(call):
    if call.get("name") not in MUTATION_TOOLS:
        return True
    output = call.get("result")
    if not isinstance(output,dict) or not output or output.get("error") or output.get("isError"):
        return False
    if output.get("success") is False or output.get("status") in ("error","failed","rejected","out_of_stock"):
        return False
    return bool(output.get("order_id")) if call.get("name") == "order.create" else True


def select_scenarios(
    scenarios: dict[str, Any],
    *,
    scenario_id: str | None = None,
    scenario_ids: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Apply the same scenario selection used by trace generation."""
    if scenario_ids:
        targets = {s.strip().casefold() for s in scenario_ids if s.strip()}
        matched = {k: v for k, v in scenarios.items() if k.casefold() in targets}
        if not matched:
            raise ValueError(f"No scenarios found matching IDs: {scenario_ids}")
        return matched
    if scenario_id:
        if scenario_id not in scenarios:
            raise ValueError(f"Scenario not found: {scenario_id}")
        return {scenario_id: scenarios[scenario_id]}
    if limit is not None:
        if limit <= 0:
            raise ValueError("--limit must be greater than zero")
        return dict(list(scenarios.items())[:limit])
    return scenarios


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Team metrics layered on the BTC reference evaluator."
    )
    parser.add_argument("--scenarios", required=True)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--scenario-id")
    parser.add_argument("--scenario-ids", help="Comma-separated scenario IDs")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--warmup-turns", type=int, default=3)
    parser.add_argument("--asr")
    parser.add_argument("--rag", help="RAG results JSON")
    parser.add_argument("--rag-qa", default=str(DEFAULT_RAG_QA))
    parser.add_argument("--memory-judge-report")
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    parser.add_argument("--tool-call-usd", type=float)
    parser.add_argument("--memory-write-usd", type=float)
    parser.add_argument("--memory-storage-usd-per-mb", type=float)
    parser.add_argument("--fixed-call-usd", type=float)
    parser.add_argument("--out", default="team_report.json")
    args = parser.parse_args()

    scenario_ids = [s.strip() for s in args.scenario_ids.split(",")] if args.scenario_ids else None
    try:
        scenarios = select_scenarios(
            REFERENCE.load_scenarios(args.scenarios),
            scenario_id=args.scenario_id,
            scenario_ids=scenario_ids,
            limit=args.limit,
        )
    except ValueError as exc:
        parser.error(str(exc))

    pricing = _pricing(args)
    system = evaluate_team(
        scenarios,
        REFERENCE.load_trace(args.trace),
        pricing=pricing,
        memory_judge_report=args.memory_judge_report,
        warmup_turns=args.warmup_turns,
    )
    report: dict[str, Any] = {
        "evaluator": "team_eval_v2",
        "reference_evaluator": str(REFERENCE_EVAL),
        "n_scenarios": len(scenarios),
        "system": system,
    }
    if args.baseline:
        report["baseline"] = evaluate_team(
            scenarios,
            REFERENCE.load_trace(args.baseline),
            pricing=pricing,
            warmup_turns=args.warmup_turns,
        )
        report["comparison"] = compare_metrics(system,report["baseline"])
    if args.asr:
        report["asr"] = REFERENCE.wer_cer(args.asr)
    if args.rag:
        report["rag"] = rag_recall(Path(args.rag_qa), Path(args.rag))

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"RQR: {system['repeat_question_rate']['value']}%")
    print(f"CCR: {system['context_carryover_rate']['value']}%")
    print(f"TSR: {system['task_success_rate']['value']}%")
    print(f"HR: {system['hallucination_rate']['value']}%")
    print(f"HR (price only): {system['hallucination_rate']['price_only']['value']}%")
    print(f"Tool-Call Accuracy: {system['tool_call_accuracy']['value']}%")
    print(f"Latency: {json.dumps(system['latency'], ensure_ascii=False)}")
    print(f"Trace health: {json.dumps(system['trace_health'], ensure_ascii=False)}")
    if "comparison" in report:
        print(f"Acceptance: {json.dumps(report['comparison'],ensure_ascii=False)}")
    print(f"Report: {output_path}")
    return 0 if system["trace_health"]["valid"] and (not args.baseline or report["baseline"]["trace_health"]["valid"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
