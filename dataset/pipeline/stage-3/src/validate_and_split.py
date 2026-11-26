#!/usr/bin/env python3
"""Validate, deduplicate, and split the synthetic telesales journeys."""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import json
import math
from pathlib import Path
import random
import re
import runpy
import shutil
import sys
from tempfile import TemporaryDirectory
import unicodedata

STAGE = Path(__file__).resolve().parents[1]
ROOT = STAGE.parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "stage-1/src"), str(ROOT)]
from common import CUSTOMERS_FILE, GENERATION_LOG_FILE, TRANSCRIPTS_FILE, find_artifact, promote_latest

CALL_KEYS = ("call_1", "call_2", "call_3")
OUTCOMES = {"chot_don", "hen_goi_lai", "tu_choi", "chuyen_may"}
CHANNELS = {"hotline", "facebook", "zalo"}
MINIMUMS = {
    "M1": (120, 30, 3, 10, 5, 20),
    "M2": (250, 60, 20, 30, 15, 40),
}
SIMILARITY_LIMIT = 0.90
LEGACY_PII_TOKEN = re.compile(r"\[(?:PHONE|ADDR(?:_ALT)?|CCCD|BANK)_CUST_\d+\]")
PII = {
    "PHONE": re.compile(r"(?<![\w+])(?:0[ .-]*[35789]|(?:\+?84)[ .-]*[35789])(?:[ .-]*\d){8}(?!\d)"),
    "CCCD": re.compile(r"(?<!\w)(?:\d[ -]?){11}\d(?!\w)"),
    "BANK": re.compile(r"(?<!\w)\d{9,14}(?!\w)"),
    "ADDR": re.compile(
        r"(?<!\w)(?:số\s+|so\s+)?\d+[a-z]?(?:/\d+)*\s+"
        r"(?:đường|duong|phố|pho|ngõ|ngo|hẻm|hem|ngách|ngach)\s+(?:[^.!?;\n]+)",
        re.I,
    ),
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def check_synthetic_privacy(row):
    for value in strings(row):
        if LEGACY_PII_TOKEN.search(value) or any(pattern.search(value) for pattern in PII.values()):
            raise ValueError(f"Unexpected PII or legacy placeholder in {row['scenario_id']}")


def call_map(row):
    return {key: row[key] for key in CALL_KEYS if key in row}


def validate(row, tier, tools, personas, quotes):
    sid = row.get("scenario_id")
    calls = call_map(row)
    if (not sid or row.get("tier") != tier or row.get("persona") not in personas
            or not row.get("customer_id") or not row.get("customer_phone")
            or not {"call_1", "call_2"} <= calls.keys()):
        raise ValueError(f"Invalid scenario header: {sid}")
    profile = row.get("simulator_profile", {})
    if tier == "M2" and (
        not all(isinstance(profile.get(k), str) and profile[k].strip()
                for k in ("persona_system_prompt", "hidden_goal"))
        or not isinstance(profile.get("patience_level"), int) or profile["patience_level"] < 1
    ):
        raise ValueError(f"Invalid simulator profile: {sid}")

    known = set()
    previous = None
    customer = quotes[row["customer_id"]]
    identities = row["customer_identities"]
    if any(identities[key] != customer[key] for key in ("phone", "fb_id", "zalo_id")):
        raise ValueError(f"Customer identity mismatch: {sid}")
    if row["customer_phone"] != identities["phone"]:
        raise ValueError(f"Customer phone mismatch: {sid}")
    region = {"North": "Hà Nội", "Central": "Đà Nẵng", "South": "Hồ Chí Minh"}[customer["dialect"]]

    for index, (key, call) in enumerate(calls.items(), 1):
        label = f"{sid}/{key}"
        turns = call.get("customer_turns")
        channel = call.get("channel")
        if (not isinstance(turns, list) or not 2 <= len(turns) <= 5
                or any(not isinstance(t, str) or not t.strip() for t in turns)
                or call.get("expected_outcome") not in OUTCOMES or channel not in CHANNELS):
            raise ValueError(f"Invalid session: {label}")
        channel_key = {"hotline": "phone", "facebook": "fb_id", "zalo": "zalo_id"}[channel]
        if call.get("channel_identity") != identities[channel_key] or call.get("session_index") != index:
            raise ValueError(f"Session identity or index mismatch: {label}")
        day = date.fromisoformat(call["date"])
        if previous is not None and ((day - previous).days <= 0 or (day - previous).days != call.get("days_later")):
            raise ValueError(f"Invalid call chronology: {label}")
        previous = day
        for field in ("must_not_ask", "must_carry_over"):
            slots = call.get(field, [])
            if not isinstance(slots, list) or not set(slots) <= known:
                raise ValueError(f"Unknown prior session slot in {label}: {field}")
        facts = call["facts_established"]
        if set(call.get("entities_multi", [])) != {k for k, v in facts.items() if isinstance(v, list)}:
            raise ValueError(f"Multi-entity declaration mismatch: {label}")
        known.update(facts)
        assertion = call["success_if"]
        tool, args = assertion["tool_called"], assertion["args_match"]
        if (tool is not None and tool not in tools.TOOLS) or not isinstance(args, dict):
            raise ValueError(f"Invalid tool assertion: {label}")
        truth = call["ground_truth_facts"]
        if not tools.catalog_search(sku=row["target_sku"])["items"]:
            raise ValueError(f"Unknown target SKU: {label}")
        for quote in [truth] + ([truth["comparison_quote"]] if "comparison_quote" in truth else []):
            sku = quote["sku"]
            inv = tools.inventory_check(sku, on=call["date"])
            if "error" in inv or inv["in_stock"] != quote["in_stock"]:
                raise ValueError(f"Invalid inventory claim: {label}")
            catalog_quote = tools.pricing_get_quote(sku, on=call["date"],
                                                    customer_phone=customer["phone"], address=region)
            if index < 3 and catalog_quote["final_price_vnd"] != quote["price_vnd"]:
                raise ValueError(f"Incorrect dated catalog quote: {label}")
            expiry = {promo["promo_code"]: promo["end"] for promo in tools.PROMOS}
            if any(expiry.get(code) != end for code, end in quote["promo_expiry_dates"].items()):
                raise ValueError(f"Incorrect promotion expiry: {label}")
        if "sku" in args and not tools.catalog_search(sku=args["sku"])["items"]:
            raise ValueError(f"Unknown asserted SKU: {label}")
        if "price_vnd" in args:
            priced = tools.pricing_get_quote(args["sku"], on=call["date"],
                                             customer_phone=customer["phone"], address=region)
            if priced["final_price_vnd"] != args["price_vnd"]:
                raise ValueError(f"Incorrect asserted price: {label}")


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
                   if not unicodedata.combining(c))


def session_text(row):
    return " ".join(turn for call in call_map(row).values() for turn in call["customer_turns"])


def vectorize(rows):
    docs = [Counter(re.findall(r"[^\W_]+", normalize(session_text(row)))) for row in rows]
    frequencies = Counter(word for doc in docs for word in doc)
    vectors = []
    for doc in docs:
        vector = {word: (1 + math.log(count)) * (1 + math.log((1 + len(docs)) / (1 + frequencies[word])))
                  for word, count in doc.items()}
        norm = math.sqrt(sum(weight ** 2 for weight in vector.values()))
        vectors.append({word: weight / norm for word, weight in vector.items()})
    return vectors


def deduplicate(rows):
    vectors = vectorize(rows)
    accepted, removed = [], []
    for index, vector in enumerate(vectors):
        candidates = (
            (sum(weight * vectors[other].get(word, 0.0) for word, weight in vector.items()), other)
            for other in accepted
        )
        score, match = max(candidates, default=(0.0, None))
        if score > SIMILARITY_LIMIT:
            removed.append({"duplicate_of": rows[match]["scenario_id"],
                            "similarity": score, "scenario": rows[index]})
        else:
            accepted.append(index)
    return [rows[index] for index in accepted], removed


def stats_for(rows):
    channels = Counter()
    outcomes = Counter()
    customer_calls = defaultdict(list)
    for row in rows:
        for call in call_map(row).values():
            channels[call["channel"]] += 1
            outcomes[call["expected_outcome"]] += 1
            customer_calls[row["customer_id"]].append(call["channel"])
    return {
        "total_journeys": len(rows),
        "total_transcripts": len(rows),
        "total_sessions": channels.total(),
        "multi_session_customers": sum(len(calls) >= 2 for calls in customer_calls.values()),
        "three_session_customers": sum(len(calls) >= 3 for calls in customer_calls.values()),
        "omnichannel_customers": sum("hotline" in calls and len(set(calls)) > 1 for calls in customer_calls.values()),
        "hard_edge_case_scenarios": sum(bool(row.get("hard_case")) for row in rows),
        "persona_distribution": dict(Counter(row["persona"] for row in rows)),
        "channel_distribution": dict(channels),
        "outcome_distribution": dict(outcomes),
    }


def below_minimum(stats, tier):
    names = ("total_sessions", "multi_session_customers", "three_session_customers",
             "omnichannel_customers", "hard_edge_case_scenarios")
    failures = [name for name, minimum in zip(names, MINIMUMS[tier]) if stats[name] < minimum]
    if tier == "M1" and stats["total_transcripts"] < 120:
        failures.append("total_transcripts")
    return failures


def split(rows, target, seed):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["customer_id"]].append(row)
    strata = defaultdict(list)
    for customer, journeys in grouped.items():
        signature = tuple(sorted(
            (row["persona"], row.get("edge_case_type") or "", len(call_map(row))) for row in journeys
        ))
        strata[signature].append(customer)
    rng = random.Random(seed)
    for customers in strata.values():
        rng.shuffle(customers)

    if target >= len(grouped):
        raise ValueError("Not enough distinct customers for both splits")
    portion = target / len(grouped)
    allocations = {key: math.floor(len(customers) * portion) for key, customers in strata.items()}
    ranked = sorted(strata, key=lambda key: (-(len(strata[key]) * portion - allocations[key]), key))
    for key in ranked[:target - sum(allocations.values())]:
        allocations[key] += 1
    held_out = {customer for key, customers in strata.items() for customer in customers[:allocations[key]]}
    memory = [row for row in rows if row["customer_id"] not in held_out]
    golden = [row for row in rows if row["customer_id"] in held_out]
    return memory, golden


def evaluator_format(row):
    converted = {key: value for key, value in row.items() if key not in CALL_KEYS}
    converted["level"] = row["tier"]
    channel_names = {"hotline": "hotline", "facebook": "chat_fanpage", "zalo": "zalo_oa"}
    converted["calls"] = {
        key: {**call, "call_date": call["date"], "channel": channel_names[call["channel"]]}
        for key, call in call_map(row).items()
    }
    return converted


def check_evaluator(golden, evaluator):
    with TemporaryDirectory(prefix="btc-golden-") as path:
        for i, row in enumerate(golden, 1):
            write_json(Path(path) / f"scenario_{i:03d}.json", row)
        loaded = evaluator["load_scenarios"](path)
        if loaded != {row["scenario_id"]: row for row in golden}:
            raise ValueError("BTC evaluator could not load the full golden set")
        # Exercise the evaluator's scenario-field access using empty traces.
        evaluator["evaluate"](loaded, {})


def recover_if_needed(rows, accepted, dropped, tier, seed, tools, personas, customers):
    if not below_minimum(stats_for(accepted), tier):
        return accepted, dropped, 0

    renderer = runpy.run_path(str(ROOT / "stage-2/src/generate.py"))
    labels, promos, _ = renderer["load_catalog"]()
    by_id = {row["scenario_id"]: row for row in rows}
    attempts = 0
    for duplicate in list(dropped):
        original = duplicate["scenario"]
        matched = by_id[duplicate["duplicate_of"]]
        blocked = {normalize(original["call_1"]["customer_turns"][0]),
                   normalize(matched["call_1"]["customer_turns"][0])}
        for _ in range(5):
            attempts += 1
            trial = json.loads(json.dumps(original))
            customer = customers[trial["customer_id"]]
            rng = random.Random(seed + attempts)
            rendered = []
            for index, call in enumerate(call_map(trial).values(), 1):
                turns, pronoun = renderer["render_session"](trial, index, customer, labels, promos, rng)
                call["customer_turns"] = turns
                rendered.append((call, turns, pronoun))
            renderer["transcript_styles"](rendered, tier, seed + attempts)
            if normalize(trial["call_1"]["customer_turns"][0]) in blocked:
                continue
            check_synthetic_privacy(trial)
            validate(trial, tier, tools, personas, customers)
            new_rows, _ = deduplicate([*accepted, trial])
            if len(new_rows) > len(accepted):
                accepted = new_rows
                break
        if not below_minimum(stats_for(accepted), tier):
            break
    return accepted, dropped, attempts


def install_export(tier, export):
    published = ROOT / "final"
    published.mkdir(exist_ok=True)
    destination = published / tier
    work = published / f".{tier}-publish"
    work.mkdir()
    staged = work / "next"
    previous = work / "previous"
    keep_backup = False
    try:
        shutil.copytree(export, staged)
        try:
            destination.rename(previous)
        except FileNotFoundError:
            pass
        try:
            staged.rename(destination)
        except BaseException:
            if previous.exists() or previous.is_symlink():
                keep_backup = True
                previous.rename(destination)
                keep_backup = False
            raise
    finally:
        if not keep_backup:
            shutil.rmtree(work)


def publish(tier, name, rows):
    entries = []
    for row in rows:
        prefix, separator, suffix = row["scenario_id"].rpartition("-")
        if prefix not in {"SC", "TEAM-SC"} or not separator or not suffix.isascii() or not suffix.isdigit():
            raise ValueError(f"Invalid synthetic export ID: {row['scenario_id']}")
        entries.append((int(suffix), row))
    if len({number for number, _ in entries}) != len(entries):
        raise ValueError("Duplicate synthetic export ID")

    export = STAGE / "exports" / name
    export.mkdir(parents=True)
    for position, (scenario_number, row) in enumerate(sorted(entries, key=lambda entry: entry[0]), 1):
        file_number = position if tier == "M1" else scenario_number
        write_json(export / f"SC-{file_number:03d}.json", row)

    install_export(tier, export)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=MINIMUMS, default="M1")
    parser.add_argument("--publish", action="store_true", help="Copy the validated export to final for this tier.")
    args = parser.parse_args()
    tier = args.tier
    upstream = (STAGE / "input").resolve(strict=True)
    upstream_log = read_json(find_artifact(upstream, GENERATION_LOG_FILE))
    if upstream_log["tier"] != tier or upstream_log["targeted_scenario_ids"]:
        parser.error("input must point to a full Stage 2 run of the requested tier")
    source = find_artifact(upstream, TRANSCRIPTS_FILE)
    raw = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    if len(raw) != upstream_log["scenario_count"] or sum(len(call_map(row)) for row in raw) != upstream_log["session_count"]:
        raise ValueError("Stage 2 output does not match its generation log")
    if len({row["scenario_id"] for row in raw}) != len(raw):
        raise ValueError("Duplicate scenario ID")
    stage1_run = ROOT / "stage-1/runs" / upstream_log["input_run"]
    registry = find_artifact(stage1_run, CUSTOMERS_FILE)
    customers = {row["customer_id"]: row for row in read_json(registry)}
    stage1 = runpy.run_path(str(ROOT / "stage-1/src/generate.py"))
    tools, personas = stage1["load_organizer"]()
    for row in raw:
        check_synthetic_privacy(row)
        validate(row, tier, tools, personas, customers)

    accepted, dropped = deduplicate(raw)
    accepted, dropped, attempts = recover_if_needed(raw, accepted, dropped, tier, upstream_log["seed"],
                                                      tools, personas, customers)
    stats = stats_for(accepted)
    if below := below_minimum(stats, tier):
        raise ValueError(f"Below tier minimum after deduplication: {', '.join(below)}")
    target = MINIMUMS[tier][-1]
    seed, custom = split(accepted, target, upstream_log["seed"])
    if len(custom) < target:
        raise ValueError("Below tier minimum for custom golden scenarios")

    data = ROOT / "btc"
    if not data.is_dir():
        data = ROOT
    sample_dir = data / "BTC-Data-Vong1-TEAMS/test_set/public_sample"
    public = [read_json(sample_dir / f"SAMPLE-{index:02d}.json") for index in range(1, 8)]
    custom_golden = [evaluator_format(row) for row in custom]
    golden = custom_golden + public
    for field in ("customer_id", "customer_phone"):
        if {row[field] for row in seed} & {row[field] for row in golden if field in row}:
            raise ValueError(f"Cross-split leakage: {field}")
    if len({row["scenario_id"] for row in golden}) != len(golden):
        raise ValueError("Duplicate scenario ID in golden output")
    violations = sum(len(pattern.findall(value)) for value in strings([seed, custom_golden, dropped])
                     for pattern in PII.values())
    if violations:
        raise ValueError(f"{violations} possible PII matches in generated journeys")
    reference = data / "BTC-cap-nhat-11-2026/eval/reference_eval.py"
    check_evaluator(golden, runpy.run_path(str(reference)))

    now = datetime.now().astimezone()
    name = f"run_{tier}_{now:%Y%m%d_%H%M}"
    run = STAGE / "runs" / name
    run.mkdir(parents=True)
    write_jsonl(run / "journeys_memory_seed.jsonl", seed)
    write_json(run / "team_golden_scenarios.json", golden)
    write_jsonl(run / "stage3_dropped_duplicates.jsonl", dropped)
    write_json(run / "pii_audit_report.json", {"tier": tier, "scope": "synthetic_journeys",
                                             "guardrail_violations": violations})
    write_json(run / "dataset_stats.json", {
        "tier": tier, "timestamp": now.isoformat(timespec="seconds"), "input_run": upstream.name,
        **stats, "memory_seed_journeys": len(seed), "golden_test_scenarios": len(custom),
        "btc_public_scenarios": len(public), "combined_golden_scenarios": len(golden),
        "guardrail_violations": violations, "duplicate_candidates": len(dropped),
        "regeneration_attempts": attempts, "cosine_threshold": SIMILARITY_LIMIT,
        "reference_eval_smoke_check": "passed",
    })
    if args.publish:
        publish(tier, name, seed + custom_golden)
    promote_latest(STAGE, name)
    print(f"{tier}: {len(seed)} seed journeys, {len(custom)} custom golden, {len(public)} BTC public in {run}")


if __name__ == "__main__":
    main()
