#!/usr/bin/env python3
"""Optional post-run LLM judge for Memory Write Quality (MWQ)."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
load_dotenv(REPO_ROOT / ".env")

from eval.team_eval import REFERENCE, select_scenarios  # noqa: E402
from telesale_agent.adapters.llm.model_factory import (  # noqa: E402
    create_chat_model,
    resolve_model_config,
)


DIMENSIONS = (
    "correctness",
    "provenance",
    "relevance",
    "atomicity",
    "non_redundancy",
    "supersession",
    "privacy",
    "actionability",
)


class MemoryJudgeResult(BaseModel):
    correctness: int = Field(ge=1, le=5)
    provenance: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    atomicity: int = Field(ge=1, le=5)
    non_redundancy: int = Field(ge=1, le=5)
    supersession: int = Field(ge=1, le=5)
    privacy: int = Field(ge=1, le=5)
    actionability: int = Field(ge=1, le=5)
    rationale: str
    unsupported_writes: list[str] = Field(default_factory=list)
    missing_high_value_facts: list[str] = Field(default_factory=list)


def _model_dict(value: BaseModel) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value.dict()


def _scenario_evidence(
    scenario: dict[str, Any],
    trace: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    scenario_id = scenario["scenario_id"]
    for call_key, call_spec in scenario.get("calls", {}).items():
        rows = trace.get((scenario_id, call_key), [])
        calls[call_key] = {
            "customer_goal": call_spec.get("customer_goal"),
            "customer_turns_ground_truth": call_spec.get("customer_turns", []),
            "facts_established_ground_truth": call_spec.get("facts_established", {}),
            "memory_expectation": call_spec.get("memory_expectation"),
            "observed_turns": [
                {
                    "turn": row.get("turn"),
                    "customer_text": row.get("customer_text"),
                    "agent_text": row.get("agent_text"),
                    "tool_calls": row.get("tool_calls", []),
                    "memory_writes": row.get("memory_writes", []),
                }
                for row in rows
            ],
        }
    return {
        "scenario_id": scenario_id,
        "persona": scenario.get("persona"),
        "notes": scenario.get("notes"),
        "calls": calls,
    }


def _prompt(evidence: dict[str, Any]) -> str:
    return f"""You are evaluating durable memory writes made by a Vietnamese telesales agent.
This is a post-run evaluation. The evidence below was never shown to the agent.

Score every dimension from 1 (bad) to 5 (excellent):
- correctness: stored values agree with customer statements or authoritative tool results.
- provenance: facts attributed to the customer were actually stated by the customer; agent suggestions must not become customer facts.
- relevance: only durable facts useful in later calls are stored.
- atomicity: facts are specific, structured and independently updateable.
- non_redundancy: no wasteful duplicates or paraphrase copies.
- supersession: corrections/newer values replace or invalidate older values correctly.
- privacy: sensitive data is minimized and written only when operationally necessary.
- actionability: useful commitments, preferences, blockers, order identifiers and follow-ups are retained.

Important rules:
1. Tool results are authoritative only for fields returned by that tool.
2. Customer turns are authoritative for customer preferences, consent and supplied details.
3. Agent text is not proof of a customer fact.
4. Do not penalize a field merely because its key name differs, if its semantics are clear.
5. If no update is necessary, not writing memory is acceptable.
6. Keep rationale concise and list unsupported writes verbatim as key/value descriptions.

Evidence:
{json.dumps(evidence, ensure_ascii=False)}
"""


async def run(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = select_scenarios(
        REFERENCE.load_scenarios(args.scenarios),
        scenario_id=args.scenario_id,
        limit=args.limit,
    )
    trace = REFERENCE.load_trace(args.trace)
    config = resolve_model_config(provider=args.provider, model_name=args.model)
    llm = create_chat_model(
        temperature=0,
        provider=config.provider,
        model_name=config.model,
        max_output_tokens=args.max_output_tokens,
    ).with_structured_output(MemoryJudgeResult)

    judgments: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, (scenario_id, scenario) in enumerate(scenarios.items()):
        if index and args.sleep > 0:
            await asyncio.sleep(args.sleep)
        try:
            result = await llm.ainvoke(_prompt(_scenario_evidence(scenario, trace)))
            row = _model_dict(result)
            row["scenario_id"] = scenario_id
            row["overall_score_5"] = round(
                statistics.mean(float(row[key]) for key in DIMENSIONS), 2
            )
            judgments.append(row)
            print(f"[MWQ] {scenario_id}: {row['overall_score_5']}/5")
        except Exception as exc:  # keep the rest of a long benchmark judgeable
            failures.append({"scenario_id": scenario_id, "error": str(exc)})
            print(f"[MWQ ERROR] {scenario_id}: {exc}", file=sys.stderr)

    dimension_means = {
        key: round(statistics.mean(float(row[key]) for row in judgments), 2)
        if judgments
        else None
        for key in DIMENSIONS
    }
    overall = (
        round(statistics.mean(row["overall_score_5"] for row in judgments), 2)
        if judgments
        else None
    )
    return {
        "status": "completed" if not failures else "completed_with_errors",
        "rubric_version": "mwq_v1",
        "judge": {"provider": config.provider, "model": config.model},
        "aggregate": {
            "value": round(overall / 5 * 100, 1) if overall is not None else None,
            "overall_score_5": overall,
            "dimension_scores_5": dimension_means,
            "scenarios_judged": len(judgments),
            "scenarios_failed": len(failures),
        },
        "judgments": judgments,
        "failures": failures,
        "note": "LLM-as-a-judge result; calibrate against a human-labeled subset.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Judge Memory Write Quality.")
    parser.add_argument("--scenarios", required=True)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--scenario-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    report = asyncio.run(run(args))
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"MWQ report: {output_path}")
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
