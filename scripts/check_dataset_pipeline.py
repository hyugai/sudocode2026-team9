"""Validate the committed Stage 3 exports using the BTC reference evaluator."""

from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = ROOT / "dataset/transcript"


def check_export(tier, numbers, expected_sessions, evaluator):
    directory = TRANSCRIPTS / tier
    filenames = [path.name for path in sorted(directory.glob("*.json"))]
    if filenames != [f"SC-{number:03d}.json" for number in numbers]:
        raise ValueError(f"{tier}: unexpected set of published scenario files in {directory}")

    scenarios = evaluator["load_scenarios"](str(directory))
    if len(scenarios) != len(numbers):
        raise ValueError(f"{tier}: the evaluator could not load distinct scenario IDs")

    sessions = 0
    for scenario_id, scenario in scenarios.items():
        calls = scenario["calls"]
        if scenario["level"] != tier or len(calls) not in (2, 3):
            raise ValueError(f"{tier}/{scenario_id}: unexpected tier or number of sessions")
        for call_id, call in calls.items():
            turns = call["customer_turns"]
            if not isinstance(turns, list) or not turns or any(
                not isinstance(turn, str) or not turn.strip() for turn in turns
            ):
                raise ValueError(f"{tier}/{scenario_id}/{call_id}: invalid customer turns")
        sessions += len(calls)
    if sessions != expected_sessions:
        raise ValueError(f"{tier}: expected {expected_sessions} sessions, found {sessions}")

    evaluator["evaluate"](scenarios, {})
    print(f"Verified {tier}: {len(scenarios)} scenarios and {sessions} sessions.")


def main():
    evaluator = runpy.run_path(str(ROOT / "dataset/organizer/eval/reference_eval.py"))
    check_export("M1", range(1, 158), 338, evaluator)
    check_export("M2", range(158, 316), 344, evaluator)


if __name__ == "__main__":
    main()
