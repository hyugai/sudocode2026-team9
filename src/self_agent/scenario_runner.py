"""Replay scenario calls and inspect post-session learning, outside benchmark."""
import argparse
import asyncio
from dataclasses import asdict
from datetime import date, timedelta
import json
from pathlib import Path
import uuid

from .models import digest, redact, sanitize

DEFAULT_SCENARIOS = Path(__file__).resolve().parents[2] / "dataset/iterative-refinement/scenarios_complete dataset"


def load_scenarios(directory, ids=(), limit=1):
    paths = sorted(Path(directory).glob("SC-*.json"))
    scenarios = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    if ids:
        missing = set(ids) - {s["scenario_id"] for s in scenarios}
        if missing:
            raise ValueError(f"Unknown scenario IDs: {sorted(missing)}")
        scenarios = [s for s in scenarios if s["scenario_id"] in ids]
    if limit:
        scenarios = scenarios[:limit]
    if not scenarios:
        raise ValueError("No scenarios selected")
    return scenarios


def artifacts(root):
    result = {}
    for group in ("gaps", "knowledge", "patterns", "regression_cases", "releases"):
        for path in (Path(root) / group).glob("*.json"):
            result[f"{group}/{path.name}"] = json.loads(path.read_text(encoding="utf-8"))
    return result


async def replay(scenarios, agent, output, *, state_factory, input_factory, cleanup=None):
    """Every call_N is a session; only customer text/identity/date enter the agent.

    No facts_established, expected_outcome, success_if or ground_truth_facts are
    passed as feedback or prompts. Customer memory is shared across calls only.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    reports = []
    for scenario in scenarios:
        reset = getattr(agent.base, "reset_customer_memory", None)
        if callable(reset):
            reset()
        created = set()
        order_map = {}
        current_date = date(2026, 10, 15)
        try:
            for call, spec in sorted(scenario["calls"].items(), key=lambda pair: int(pair[0].split("_")[-1])):
                sid = f"self-{run_id}-{scenario['scenario_id']}-{call}"
                state = state_factory(sid)
                current_date = date.fromisoformat(spec["call_date"]) if spec.get("call_date") else current_date + timedelta(days=int(spec.get("days_later", 0)))
                before = artifacts(agent.config.root)
                turns = []
                turn_results = []
                report = {"scenario_id": scenario["scenario_id"], "call": call, "session_id": sid, "turns": turns}
                try:
                    for text in spec.get("customer_turns_asr") or spec.get("customer_turns", []):
                        for expected, actual in order_map.items():
                            text = text.replace(expected, actual)
                        result = await agent.run_turn(input_factory(sid, text=text,
                            customer_hint=scenario.get("customer_phone"),
                            metadata={"call_date": current_date.isoformat(), "scenario_id": scenario["scenario_id"], "call_key": call}), state)
                        state = result.state
                        turn_results.append(result)
                        turns.append({"customer": redact(text), "agent": redact(result.response_text or ""),
                                      "latency": result.latency})
                        for tool in result.tool_calls or []:
                            if tool.get("name") in {"order.create", "create_new_order"}:
                                order_id = (tool.get("result") or {}).get("order_id")
                                if order_id:
                                    created.add(str(order_id))
                                    expected = spec.get("facts_established", {}).get("order_id")
                                    if expected:
                                        order_map[str(expected)] = str(order_id)
                    job = await agent.end_session(state, turn_results=turn_results)
                    report["job"] = asdict(await agent.wait_learning(job.job_id)) if job.job_id else asdict(job)
                    if job.job_id and agent.memory:
                        stored_job = agent.memory.read("jobs", job.job_id)
                        if stored_job.get("error_details"):
                            report["error_details"] = stored_job["error_details"]
                        try:
                            report["learning"] = agent.memory.read("reports", job.job_id)
                        except FileNotFoundError:
                            report["learning"] = None
                except Exception as exc:
                    report["error"] = type(exc).__name__
                    # An incomplete call is not silently treated as a completed session.
                after = artifacts(agent.config.root)
                report["artifact_changes"] = [
                    {"path": name, "change": "created" if name not in before else "updated", "value": value}
                    for name, value in after.items() if name not in before or digest(value) != digest(before[name])]
                target = output / f"{scenario['scenario_id']}-{call}.json"
                report = sanitize(report, [scenario.get("customer_name"), scenario.get("customer_phone")])
                target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                reports.append(report)
                print(f"{scenario['scenario_id']}/{call}: job={report.get('job', {}).get('status', 'error')}, "
                      f"changed={len(report['artifact_changes'])}; {target}")
                if report.get("error") or report.get("job", {}).get("status") in {"failed", "enqueue_failed"}:
                    raise RuntimeError(f"Session failed ({report.get('job', {}).get('error') or report.get('error')}); inspect {target}")
        finally:
            if cleanup and created:
                await asyncio.to_thread(cleanup, created)
    return reports


async def run(args, scenarios):
    from dotenv import load_dotenv
    load_dotenv()
    from .config import LearningConfig
    from .harness import SelfAgentHarness
    config = LearningConfig.from_env()
    if not config.enabled:
        raise ValueError("Set KNOWLEDGE_GAP_LOOP_ENABLED=true to inspect learning")
    from telesale_agent.bootstrap import build_deepagent_harness
    from telesale_agent.core.models import ConversationState, TurnInput
    from telesale_agent.adapters.db.client import db_client
    # In-memory customer repository: no writes to durable customer memory.
    # Read-only seed and business tools still use the configured DB/Pinecone.
    async with SelfAgentHarness(build_deepagent_harness(memory_mode="evaluation"), config=config) as agent:
        await replay(scenarios, agent, args.output, state_factory=ConversationState,
                     input_factory=TurnInput, cleanup=db_client.delete_orders)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--scenario-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=1, help="Number of scenarios; 0 means all")
    parser.add_argument("--output", type=Path, default=Path("outputs/self-agent") / uuid.uuid4().hex)
    parser.add_argument("--list", action="store_true", help="Inspect selection without model/DB calls")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    scenarios = load_scenarios(args.scenarios, args.scenario_id, args.limit)
    if args.list:
        for scenario in scenarios:
            print(scenario["scenario_id"], {k: len(v.get("customer_turns", [])) for k, v in scenario["calls"].items()})
        return
    asyncio.run(run(args, scenarios))


if __name__ == "__main__":
    main()
