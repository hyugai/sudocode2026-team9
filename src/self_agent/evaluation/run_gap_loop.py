"""Paired quality report; judge supplied by caller, never used as learning input."""
import argparse
import json
from pathlib import Path


def compare(round0, round1):
    if not round0 or set(round0) != set(round1):
        raise ValueError("Both rounds must contain exactly the same nonempty test IDs")
    if any(type(v) is not bool for v in [*round0.values(), *round1.values()]):
        raise ValueError("Verdicts must be booleans")
    repaired = sum(not round0[k] and round1[k] for k in round0)
    regressed = sum(round0[k] and not round1[k] for k in round0)
    failed = sum(not v for v in round0.values())
    return {"count": len(round0), "round0_pass_rate": sum(round0.values()) / len(round0),
            "round1_pass_rate": sum(round1.values()) / len(round1),
            "delta_percentage_points": 100 * (sum(round1.values()) - sum(round0.values())) / len(round0),
            "repaired": repaired, "regressed": regressed,
            "repair_rate": repaired / failed if failed else None}


async def evaluate(cases, run_round, learn, judge):
    """run_round(version, cases) must use fresh, equivalent customer memory.

    The learner receives only outputs, not cases' expected answers. Its report
    and waiting time are deliberately outside run_round timing.
    """
    before = await run_round(0, cases)
    learning_report = await learn(before)
    after = await run_round(1, cases)
    return {"quality": compare({c["id"]: judge(c, before[c["id"]]) for c in cases},
                               {c["id"]: judge(c, after[c["id"]]) for c in cases}),
            "learning": learning_report}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare two fixed-test verdict JSON objects")
    parser.add_argument("round0")
    parser.add_argument("round1")
    args = parser.parse_args()
    print(json.dumps(compare(*(json.loads(Path(p).read_text(encoding="utf-8"))
                               for p in (args.round0, args.round1))), indent=2))
