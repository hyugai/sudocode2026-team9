"""Compare Stage 1 blueprints by their structured scenario behavior."""

import json
from pathlib import Path
import re


def blueprint_signature(blueprint):
    sessions = []
    previous = None
    for key in ("call_1", "call_2", "call_3"):
        if key not in blueprint:
            continue
        call = blueprint[key]
        success = call["success_if"]
        truth = call["ground_truth_facts"]
        facts = call["facts_established"]
        products = facts.get("product_advised")
        previous_promos = set(previous.get("active_promos", ())) if previous else set()
        price_changed = previous is not None and previous.get("price_vnd") != truth.get("price_vnd")
        sessions.append((
            call["channel"], call["expected_outcome"], success["tool_called"],
            success["args_match"].get("action"),
            len(products) if isinstance(products, list) else 1,
            tuple(sorted(facts.get("basket_skus", ()))),
            truth.get("in_stock"), price_changed,
            bool(previous_promos.intersection(truth.get("expired_promos", ()))),
            truth.get("policy_reference"),
        ))
        previous = truth
    return blueprint["target_sku"], tuple(sessions)


def is_duplicate_blueprint(blueprint, signatures):
    return blueprint_signature(blueprint) in signatures


def read_blueprint_reference(path: Path, *, expected_tier: str | None = None):
    """Read signatures and the largest scenario number from one archived batch."""
    signatures, scenario_numbers = set(), set()
    required = {"call_1", "call_2"}
    label = f"Stage 1 {expected_tier} blueprint" if expected_tier else "Stage 1 blueprint"
    with path.open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                tier = row.get("tier") if isinstance(row, dict) else None
                if tier not in ("M1", "M2") or (expected_tier and tier != expected_tier):
                    raise ValueError("unexpected tier")
                match = re.fullmatch(r"(?:TEAM-)?SC-([0-9]+)", row["scenario_id"])
                if not match or not required <= row.keys():
                    raise ValueError("invalid scenario ID or missing sessions")
                scenario_number = int(match[1])
                if scenario_number in scenario_numbers:
                    raise ValueError(f"duplicate scenario number {scenario_number}")
                signatures.add(blueprint_signature(row))
                scenario_numbers.add(scenario_number)
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Expected a {label} in {path}, line {number}: {error}") from error
    if not scenario_numbers:
        raise ValueError(f"The blueprint reference is empty: {path}")
    return signatures, max(scenario_numbers)
