"""Join accepted transcripts to Stage 1 and export BTC scenarios."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import runpy
from tempfile import TemporaryDirectory

from validate_and_split import (
    LEGACY_PII_TOKEN, MINIMUMS, PII, SIMILARITY_LIMIT, below_minimum, call_map,
    check_evaluator, deduplicate, normalize, read_json, stats_for, strings, write_json,
    write_jsonl,
)


CHANNELS = {"hotline": "hotline", "facebook": "chat_fanpage", "zalo": "zalo_oa"}
IDENTITIES = {"hotline": "phone", "facebook": "fb_id", "zalo": "zalo_id"}
SESSION_FIELDS = (
    "days_later", "customer_goal", "customer_turns_asr", "input_mode", "seed_history",
    "facts_established", "must_carry_over", "must_not_ask", "ground_truth_facts",
    "memory_expectation", "expected_outcome", "success_if",
)
STREET = re.compile(r"\b\d+[a-z]?(?:/\d+)*\s+(?:duong|pho|ngo|hem|ngach)\s+[^\n,;.?!]+")


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
        # Vietnamese turns can say "ngõ 282 Kim Giang" for "ngõ 282 đường Kim Giang".
        yield " ".join(word for word in match[0].split() if word not in ("duong", "pho"))


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


def split_journeys(rows, target, public):
    def stratum(row):
        return row["persona"], row["edge_case_type"], len(call_map(row))

    public_phones = {phone_key(row["customer_phone"]) for row in public if row.get("customer_phone")}
    groups = defaultdict(list)
    for row in rows:
        groups[phone_key(row["customer_phone"])].append(row)
    golden = [row for phone in sorted(groups.keys() & public_phones) for row in groups.pop(phone)]

    counts = Counter(map(stratum, rows))
    desired = {kind: count * max(target, len(golden)) / len(rows) for kind, count in counts.items()}
    selected = Counter(map(stratum, golden))

    def gain(group):
        return sum(
            abs(desired[kind] - selected[kind]) - abs(desired[kind] - selected[kind] - count)
            for kind, count in Counter(map(stratum, group)).items()
        )

    while len(golden) < target and len(groups) > 1:
        phone = max(groups, key=lambda key: gain(groups[key]))
        group = groups.pop(phone)
        golden.extend(group)
        selected.update(map(stratum, group))

    memory = [row for group in groups.values() for row in group]
    if len(golden) < target or not memory:
        raise ValueError("There are too few distinct customer groups for both splits.")
    if {row["customer_id"] for row in memory} & {row["customer_id"] for row in golden}:
        raise ValueError("A customer appears in both splits.")
    return sorted(memory, key=lambda row: row["scenario_id"]), sorted(golden, key=lambda row: row["scenario_id"])


def export(output, scenarios, memory, golden, drops, audit, stats):
    with TemporaryDirectory(prefix=".stage-3-", dir=output.parent) as temporary:
        staged = Path(temporary) / "output"
        staged.mkdir()
        for row in scenarios:
            write_json(staged / f'{row["scenario_id"].removeprefix("TEAM-")}.json', row)
        splits = staged / "splits"
        splits.mkdir()
        write_jsonl(splits / "journeys_memory_seed.jsonl", memory)
        write_json(splits / "team_golden_scenarios.json", golden)
        reports = staged / "audit"
        reports.mkdir()
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


def finalize(input_dir, output, *, btc_dir, venue_catalog, batch_size):
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
    public_dir = organizer / "test_set/public_sample"
    public = [read_json(public_dir / f"SAMPLE-{number:02d}.json") for number in range(1, 8)]
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
    if failures := below_minimum(stats, tier):
        raise ValueError(f"{tier} minimums failed: {', '.join(failures)}. Privacy rejections: {len(rejected)}.")
    memory, golden = split_journeys(retained, MINIMUMS[tier][-1], public)
    individual = [scenarios[row["scenario_id"]] for row in retained]
    if len({row["scenario_id"].removeprefix("TEAM-") for row in individual}) != len(individual):
        raise ValueError("Journey filenames are not unique.")
    memory = [scenarios[row["scenario_id"]] for row in memory]
    custom_golden = [scenarios[row["scenario_id"]] for row in golden]
    golden = custom_golden + public
    if len({row["scenario_id"] for row in golden}) != len(golden):
        raise ValueError("Golden scenario IDs are not unique.")

    evaluator = runpy.run_path(str(btc_dir / "BTC-cap-nhat-11-2026/eval/reference_eval.py"))
    check_evaluator(individual, evaluator)
    check_evaluator(golden, evaluator)
    drops = [
        {"scenario_id": row["scenario"]["scenario_id"], "duplicate_of": row["duplicate_of"],
         "similarity": row["similarity"]}
        for row in duplicates
    ]
    audit = {"scope": "synthetic_journeys", "checked_journeys": len(accepted),
             "guardrail_violations": 0, "rejected_journeys": rejected}
    stats.update(tier=tier, accepted_transcripts=len(accepted), memory_seed_journeys=len(memory),
                 golden_test_scenarios=len(custom_golden), btc_public_scenarios=len(public),
                 combined_golden_scenarios=len(golden), duplicates_removed=len(drops),
                 privacy_rejections=len(rejected), guardrail_violations=0,
                 cosine_threshold=SIMILARITY_LIMIT, reference_eval_smoke_check="passed")
    export(output, individual, memory, golden, drops, audit, stats)
    return stats
