"""Join accepted transcripts to Stage 1 and export BTC scenarios."""

import json
from pathlib import Path
import re
import runpy
from tempfile import TemporaryDirectory

from validate_and_split import (
    LEGACY_PII_TOKEN, MINIMUMS, PII, SIMILARITY_LIMIT, below_minimum, call_map,
    check_evaluator, deduplicate, normalize, numbered_scenarios, read_json,
    stats_for, strings, write_json, write_jsonl,
)


CHANNELS = {"hotline": "hotline", "facebook": "chat_fanpage", "zalo": "zalo_oa"}
IDENTITIES = {"hotline": "phone", "facebook": "fb_id", "zalo": "zalo_id"}
SESSION_FIELDS = (
    "days_later", "customer_goal", "customer_turns_asr", "input_mode", "seed_history",
    "facts_established", "must_carry_over", "must_not_ask", "ground_truth_facts",
    "memory_expectation", "expected_outcome", "success_if",
)
STREET = re.compile(
    r"\b(?P<number>\d+[a-z]?(?:/\d+)*)(?:\s*,\s*|\s+)"
    r"(?P<street>(?:duong|pho|ngo|hem|ngach)\s+[^\n,;.?!]+)"
)


def read_jsonl(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def assemble(transcript, blueprint, customer):
    sid = transcript["scenario_id"]
    calls = call_map(blueprint)
    if transcript.keys() - {"scenario_id"} != calls.keys() or len(calls) not in (2, 3):
        raise ValueError(f"Session keys differ for {sid}.")

    sessions = {}
    for key, planned in calls.items():
        accepted = transcript[key]
        channel = planned["channel"]
        if accepted["channel"] != channel or planned["channel_identity"] != customer[IDENTITIES[channel]]:
            raise ValueError(f"Channel or identity mismatch for {sid}/{key}.")
        sessions[key] = {
            "channel": CHANNELS[channel],
            "channel_identity": planned["channel_identity"],
            "call_date": planned["date"],
            "customer_turns": accepted["customer_turns"],
            **{field: planned[field] for field in SESSION_FIELDS if field in planned},
        }

    return {
        "scenario_id": sid,
        "level": blueprint["tier"],
        "persona": blueprint["persona"],
        "hard_case": blueprint["edge_case_type"] if blueprint["hard_case"] else None,
        "customer_phone": customer["phone"],
        "customer_name": customer.get("name") or f'Khách {customer["customer_id"]}',
        "honorific": customer.get("honorific") or "anh/chị",
        "notes": blueprint.get("journey_pattern") or blueprint.get("edge_case_type") or "",
        "calls": sessions,
    }


def phone_key(value):
    digits = re.sub(r"\D", "", value)
    return "0" + digits[2:] if len(digits) == 11 and digits.startswith("84") else digits


def street_keys(value):
    for match in STREET.finditer(normalize(value)):
        number = re.sub(r"\b0+(?=\d)", "", match["number"])
        # Vietnamese turns can say "ngõ 282 Kim Giang" for "ngõ 282 đường Kim Giang".
        words = [word for word in match["street"].split() if word not in ("duong", "pho")]
        yield " ".join([number, *words])


def privacy_findings(scenario, customer, crm, venues):
    flagged = set()
    fixture = crm.get(customer["customer_id"], {})
    mock_phone = re.fullmatch(r"000-000-\d{4}", customer["phone"])
    identity_fields = ("phone", "name", "honorific", "fb_id", "zalo_id")
    if not mock_phone and any(customer.get(field) != fixture.get(field) for field in identity_fields):
        flagged.add("unrecognized_customer_identity")

    allowed_phone = phone_key(customer["phone"])
    allowed_streets = set()
    venue = venues.get(customer.get("address_reference_id"), {})
    for field in ("address", "alternate_address"):
        value = customer.get(field)
        if value and value == venue.get(field):
            allowed_streets.update(street_keys(value))

    for value in strings(scenario):
        if LEGACY_PII_TOKEN.search(value):
            flagged.add("legacy_placeholder")
        for kind in ("PHONE", "CCCD", "BANK"):
            if any(phone_key(match[0]) != allowed_phone for match in PII[kind].finditer(value)):
                flagged.add(kind.lower())
        for street in street_keys(value):
            if not any(street == known or street.startswith(known + " ") for known in allowed_streets):
                flagged.add("unrecognized_numbered_street")
    return sorted(flagged)


def export(output, scenarios, drops, audit, stats):
    files = numbered_scenarios(stats["tier"], scenarios)
    renamed = []
    with TemporaryDirectory(prefix=".stage-3-", dir=output.parent) as temporary:
        staged = Path(temporary) / "output"
        staged.mkdir()
        for filename, row in files:
            scenario_id = row["scenario_id"]
            if filename != f'{scenario_id.removeprefix("TEAM-")}.json':
                renamed.append({"original_scenario_id": scenario_id, "new_filename": filename})
            write_json(staged / filename, row)
        reports = staged / "audit"
        reports.mkdir()
        write_jsonl(reports / "renamed_scenarios.jsonl", renamed)
        write_jsonl(reports / "stage3_dropped_duplicates.jsonl", drops)
        write_json(reports / "pii_audit_report.json", audit)
        write_json(reports / "dataset_stats.json", stats)

        previous = Path(temporary) / "previous"
        if output.is_dir():
            output.rename(previous)
        try:
            staged.rename(output)
        except OSError:
            if previous.exists():
                previous.rename(output)
            raise


def finalize(input_dir, output, *, btc_dir, venue_catalog, batch_size, allow_m2_multi_session_shortfall=False):
    if batch_size < 1:
        raise ValueError("BATCH_SIZE must be positive.")
    accepted = read_jsonl(input_dir / "transcripts.jsonl")
    blueprints = {row["scenario_id"]: row for row in read_jsonl(input_dir / "blueprints.jsonl")}
    customers = {row["customer_id"]: row for row in read_json(input_dir / "customers.json")}
    tiers = {blueprints[row["scenario_id"]]["tier"] for row in accepted}
    if len(tiers) != 1 or len(accepted) != len({row["scenario_id"] for row in accepted}):
        raise ValueError("Use a nonempty Stage 2 file with unique scenarios from one tier.")
    tier = tiers.pop()

    organizer = btc_dir / "BTC-Data-Vong1-TEAMS"
    crm = {row["customer_id"]: row for row in read_json(organizer / "catalog/crm_seed.json")["customers"]}
    venues = {row["reference_id"]: row for row in read_json(venue_catalog)}
    eligible, rejected = [], []
    scenarios = {}
    accepted.sort(key=lambda row: row["scenario_id"])

    for start in range(0, len(accepted), batch_size):
        batch = accepted[start:start + batch_size]
        for transcript in batch:
            sid = transcript["scenario_id"]
            if not re.fullmatch(r"(?:TEAM-)?SC-\d{3,}", sid):
                raise ValueError(f"Unexpected scenario ID: {sid}")
            blueprint = blueprints[sid]
            customer = customers[blueprint["customer_id"]]
            scenario = assemble(transcript, blueprint, customer)
            findings = privacy_findings(scenario, customer, crm, venues)
            if findings:
                rejected.append({"scenario_id": sid, "findings": findings})
                continue

            scenarios[sid] = scenario
            # Use the existing TF-IDF and tier checks on the joined blueprint layout.
            eligible.append({**blueprint, "customer_phone": customer["phone"], **{
                key: {**blueprint[key], "customer_turns": call["customer_turns"]}
                for key, call in scenario["calls"].items()
            }})
        print(f"Processed {start + len(batch)}/{len(accepted)} journeys")

    retained, duplicates = deduplicate(eligible)
    stats = stats_for(retained)
    stats["three_session_customers"] = len({
        row["customer_id"] for row in retained if len(call_map(row)) == 3
    })
    stats["channel_distribution"] = {
        CHANNELS[channel]: count for channel, count in stats["channel_distribution"].items()
    }
    failures = below_minimum(stats, tier)
    if tier == "M2" and allow_m2_multi_session_shortfall and "multi_session_customers" in failures:
        failures.remove("multi_session_customers")
        _, minimum_customers, *_ = MINIMUMS[tier]
        stats["deferred_minimums"] = {
            "multi_session_customers": {"actual": stats["multi_session_customers"], "minimum": minimum_customers},
        }
    if failures:
        raise ValueError(f"{tier} minimums failed: {', '.join(failures)}. Privacy rejections: {len(rejected)}.")
    individual = [scenarios[row["scenario_id"]] for row in retained]
    evaluator = runpy.run_path(str(btc_dir / "BTC-cap-nhat-11-2026/eval/reference_eval.py"))
    check_evaluator(individual, evaluator)
    drops = [
        {"scenario_id": row["scenario"]["scenario_id"], "duplicate_of": row["duplicate_of"],
         "similarity": row["similarity"]}
        for row in duplicates
    ]
    audit = {"scope": "synthetic_journeys", "checked_journeys": len(accepted),
             "guardrail_violations": 0, "rejected_journeys": rejected}
    stats.update(tier=tier, accepted_transcripts=len(accepted), duplicates_removed=len(drops),
                 privacy_rejections=len(rejected), guardrail_violations=0,
                 cosine_threshold=SIMILARITY_LIMIT, reference_eval_smoke_check="passed")
    export(output, individual, drops, audit, stats)
    return stats
