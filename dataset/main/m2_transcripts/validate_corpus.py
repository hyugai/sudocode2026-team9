#!/usr/bin/env python3
"""Independently inspect persisted fixtures, replay tools, and audit M2 counts.

This is fixture validation, not an evaluation of a model or sales agent.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from build_corpus import HERE, MAIN, ORGANIZER, SCENARIO_FIELDS, read, reference_module


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def rows_for(transcript):
    tools = transcript["private_annotations"]["reference_tool_executions"]
    return [{"agent_text": u["text"], "tool_calls": [tools[i] for i in u.get("tool_refs", [])], "questions": [{"slot": "scripted_confirmation", "kind": "confirm"}] * u["text"].count("?")} for u in transcript["utterances"] if u["speaker"] == "agent"]


def replay(mock, tools):
    """Return errors without accepting a recorded tool result as its own truth."""
    errors = []
    for index, tc in enumerate(tools):
        if tc["name"] not in mock.TOOLS:
            errors.append(f"unknown tool at {index}: {tc['name']}")
            continue
        result = mock.TOOLS[tc["name"]](**tc["args"])
        if result != tc["result"]:
            errors.append(f"reference result differs at tool {index}: {tc['name']}")
        if result.get("error"):
            errors.append(f"unexpected tool failure at {index}: {result['error']}")
    return errors


def negative_order_probes(evaluator, spec, rows):
    """A correct fixture must fail if creation failed or an item disappeared."""
    if spec["success_if"].get("tool_called") != "order.create":
        return [], 0
    errors = []
    bad = copy.deepcopy(rows)
    for row in bad:
        for tc in row["tool_calls"]:
            if tc["name"] == "order.create":
                tc["result"] = {"error": "price_mismatch"}
    if evaluator.check_call(spec, bad)[0]:
        errors.append("evaluator accepted a failed creation")
    probes = 1
    if spec["success_if"].get("also_ordered"):
        bad = copy.deepcopy(rows)
        for row in bad:
            for tc in row["tool_calls"]:
                if tc["name"] == "order.create":
                    tc["args"]["lines"] = tc["args"]["lines"][:-1]
        if evaluator.check_call(spec, bad)[0]:
            errors.append("evaluator accepted a missing order unit")
        probes += 1
    return errors, probes


def validate(root: Path = HERE) -> dict:
    root = Path(root)
    errors = []
    manifest = jsonl(root / "manifest.jsonl")
    plan = jsonl(root / "recording_plan.jsonl")
    requirements = read(root / "requirements.json")
    coverage = read(root / "coverage.json")
    catalog = read(root / "catalog_skus.json")
    customers = {c["customer_id"]: c for c in read(root / "customers.json")["customers"]}
    scenarios = {p.stem: read(p) for p in sorted((root / "scenarios_complete").glob("*.json"))}
    scenario_metadata = read(root / "scenario_metadata.json")
    source_scenario_ids = {path.stem for path in (MAIN / "scenarios_complete").glob("SC-*.json")}
    source_max = max(int(sid.split("-")[1]) for sid in source_scenario_ids)
    reference_call_fields = {key for path in (MAIN / "scenarios_complete").glob("*.json") for call in read(path)["calls"].values() for key in call}
    reference = reference_module("btc_corpus_validation", "mock_tools.py")
    evaluator = reference_module("btc_corpus_evaluation", "reference_eval.py")
    base_crm = copy.deepcopy(reference.CRM)
    by_transcript = {}
    sessions = defaultdict(list)
    channel_sets = defaultdict(set)
    customer_three = set()
    customer_linked_channels = set()
    customer_two_hotline = set()
    channels = Counter()
    personas = Counter()
    categories_used = set()
    tools_replayed = 0
    positive_checks = 0
    negative_checks = 0
    utterance_count = 0

    def check(condition, detail):
        if not condition:
            errors.append(detail)

    expected_scenario_ids = {f"SC-{number:03d}" for number in range(source_max + 1, source_max + 1 + len(scenarios))}
    check(set(scenarios) == expected_scenario_ids, "M2 scenario IDs must continue incrementally after the original maximum")
    check(not (set(scenarios) & source_scenario_ids), "M2 scenario IDs overlap original scenario IDs")
    numbering = {
        "source_max_scenario_id": f"SC-{source_max:03d}",
        "first_scenario_id": min(scenarios),
        "last_scenario_id": max(scenarios),
        "count": len(scenarios),
    }
    check(coverage["numbering"] == numbering, "coverage scenario numbering differs")

    for entry in manifest:
        tid = entry["transcript_id"]
        check(tid not in by_transcript, f"duplicate manifest ID {tid}")
        transcript_path = root / entry["conversation_path"]
        t = read(transcript_path)
        by_transcript[tid] = t
        check(tid == t["transcript_id"] == transcript_path.stem, f"transcript filename/ID mismatch {tid}")
        check(hashlib.sha256(transcript_path.read_bytes()).hexdigest() == entry["conversation_sha256"], f"manifest checksum mismatch {tid}")
        check(t["origin"] == "authored_synthetic_reference_dialogue" and t["is_actual_agent_trace"] is False, f"misrepresented origin {tid}")
        check(entry["actual_agent_trace"] is False and entry["audio_path"] is None, f"misrepresented measurements {tid}")
        for key in ("scenario_id", "call", "customer_id", "channel"):
            check(t[key] == entry[key], f"manifest metadata mismatch {tid}: {key}")
        speakers = [u["speaker"] for u in t["utterances"]]
        check(speakers == ["customer", "agent"] * (len(speakers) // 2), f"speaker sequence {tid}")
        check(all(u["text"].strip() for u in t["utterances"]), f"empty utterance {tid}")
        check(set(speakers) == {"agent", "customer"}, f"missing speaker {tid}")
        check(speakers.count("customer") == entry["customer_turns"] <= 12, f"customer turn count / simulator cap {tid}")
        check(speakers.count("agent") == entry["agent_turns"], f"agent turn count {tid}")
        check(sum(len(u["text"].split()) for u in t["utterances"]) == entry["word_count"], f"word count {tid}")
        check((root / entry["script_path"]).exists(), f"missing reading script {tid}")
        check(entry["scenario_path"] == f"scenarios_complete/{entry['scenario_id']}.json", f"scenario manifest path {tid}")
        check((root / entry["scenario_path"]).exists(), f"missing scenario {tid}")
        check(entry["customer_id"] in customers, f"unknown customer {tid}")
        sessions[entry["customer_id"]].append(tid)
        channel_sets[entry["customer_id"]].add(entry["channel"])
        channels[entry["channel"]] += 1
        utterance_count += len(speakers)
        agent_text = " ".join(u["text"] for u in t["utterances"] if u["speaker"] == "agent")
        check(not re.search(r"\b0\d{9}\b", agent_text), f"agent repeats a full phone {tid}")
        check(not re.search(r"\b\d+ đường Kiểm Thử", agent_text), f"agent repeats a street number {tid}")
        check(not any(u.get("start") is not None or u.get("end") is not None for u in t["utterances"]), f"fabricated segment timestamps {tid}")
        check(t["private_annotations"]["review_status"].endswith("human_semantic_review_pending"), f"unsupported review claim {tid}")

    for sid, s in scenarios.items():
        check(bool(re.fullmatch(r"SC-\d{3}", sid)), f"scenario filename format {sid}")
        check(tuple(s) == SCENARIO_FIELDS, f"scenario fields differ from scenarios_complete reference {sid}")
        meta = scenario_metadata[sid]
        fixture = meta["fixture"]
        check(sid == s["scenario_id"] and s["level"] == "M2", f"scenario identity/level {sid}")
        check(2 <= len(s["calls"]) <= 3, f"journey length {sid}")
        cid = fixture["customer_id"]
        personas[s["persona"]] += 1
        if len(s["calls"]) >= 3:
            customer_three.add(cid)
        journey_channels = {c["channel"] for c in s["calls"].values()}
        if "hotline" in journey_channels and len(journey_channels) > 1:
            customer_linked_channels.add(cid)
        if sum(c["channel"] == "hotline" for c in s["calls"].values()) >= 2:
            customer_two_hotline.add(cid)
        if fixture["new_customer"]:
            check(s["customer_phone"] not in {c["phone"] for c in base_crm}, f"new customer reuses BTC phone {sid}")
            check(cid not in {c["customer_id"] for c in base_crm}, f"new customer reuses BTC customer_id {sid}")
        if meta.get("source_scenario_id"):
            source = MAIN / "scenarios_complete" / f"{meta['source_scenario_id']}.json"
            check(hashlib.sha256(source.read_bytes()).hexdigest() == fixture["source_complete_sha256"], f"original source modified {sid}")
        reference.CRM = copy.deepcopy(base_crm)
        reference._ORDERS.clear()
        reference._ONCE_USED.clear()
        reference._TICKETS.clear()
        reference._CALLBACKS.clear()
        aliases = set()
        prior_date = ""
        known = {}
        for call_id, c in s["calls"].items():
            tid = f"{sid}-{call_id}"
            check(set(c) <= reference_call_fields, f"call fields differ from scenarios_complete reference {tid}")
            check(meta["transcript_refs"][call_id] == f"../conversations/{tid}.json", f"transcript sidecar reference {tid}")
            t = by_transcript[tid]
            check(t["customer_id"] == cid, f"customer changes within journey {tid}")
            check(c["call_date"] > prior_date, f"non-increasing session dates {tid}")
            prior_date = c["call_date"]
            outline = [u["text"] for u in t["utterances"] if u["speaker"] == "customer"]
            check(c["customer_turns"] == outline, f"scenario/recording outline differs {tid}")
            check("utterances" not in c and "agent_turns" not in c, f"agent answer leaked into scenario input {tid}")
            if "customer_turns_asr" in c:
                check(len(c["customer_turns_asr"]) == len(outline), f"noisy outline length {tid}")
                check(c["input_mode"] != "clean", f"unused noisy outline {tid}")
            tools = t["private_annotations"]["reference_tool_executions"]
            used = [i for u in t["utterances"] if u["speaker"] == "agent" for i in u["tool_refs"]]
            check(used == list(range(len(tools))), f"tool chronology / attribution {tid}")
            for tc in tools:
                if "on" in tc["args"]:
                    check(tc["args"]["on"] == c["call_date"], f"wall-clock tool date {tid}")
                sku = tc["args"].get("sku")
                if sku:
                    p, _ = reference._parent(sku)
                    if p:
                        categories_used.add(p["category"].split("/")[0])
            errors.extend(f"{tid}: {e}" for e in replay(reference, tools))
            tools_replayed += len(tools)
            rows = rows_for(t)
            passed, reasons = evaluator.check_call(c, rows, aliases)
            check(passed, f"fixture does not satisfy its assertions {tid}: {reasons}")
            positive_checks += 1
            negative, n = negative_order_probes(evaluator, c, rows)
            errors.extend(f"{tid}: {e}" for e in negative)
            negative_checks += n
            aliases.update(evaluator.created_order_ids(rows))
            provenance = t["private_annotations"]["fact_provenance_after_call"]
            known.update(c["facts_established"])
            for key, value in known.items():
                check(provenance[key]["value"] == value, f"stale fact after correction {tid}: {key}")
                check(provenance[key]["source_session"] in {f"{sid}-{k}" for k in s["calls"] if k <= call_id}, f"future/cross-customer fact provenance {tid}: {key}")
            for ref in t["private_annotations"]["source_refs"]:
                check((ORGANIZER / ref.split("#")[0]).exists(), f"missing knowledge source {tid}: {ref}")

    expected_tids = {f"{sid}-{cid}" for sid, s in scenarios.items() for cid in s["calls"]}
    check(set(scenario_metadata) == set(scenarios), "scenario metadata membership differs")
    check(set(by_transcript) == expected_tids, "scenario/manifest membership differs")
    check({p.stem for p in (root / "conversations").glob("*.json")} == expected_tids, "extra/missing conversation file")
    check({p.stem for p in (root / "scripts").glob("*.md")} == set(scenarios), "extra/missing reading script")
    sku_rows = catalog["items"]
    check(len({r["sku"] for r in sku_rows}) == len(sku_rows), "catalog counts a SKU twice")
    parents_with_variants = {p["sku"] for p in reference.PRODUCTS if p["variants"]}
    check(not ({r["sku"] for r in sku_rows} & parents_with_variants), "catalog double-counts variant parents")
    for row in sku_rows:
        p, v = reference._parent(row["sku"])
        check(p is not None, f"invented SKU {row['sku']}")
        if p:
            check(row["list_price_vnd"] == p["list_price_vnd"] + (v["price_delta_vnd"] if v else 0), f"catalog price differs {row['sku']}")
    for rel, digest in coverage["source_sha256"].items():
        check(hashlib.sha256((ORGANIZER / rel).read_bytes()).hexdigest() == digest, f"source hash drift {rel}")
    counts = {"scenarios": len(scenarios), "transcripts": len(manifest), "utterances": utterance_count, "customers": len(customers), "multi_session_customers": sum(len(ids) >= 2 for ids in sessions.values()), "customers_with_three_call_journey": len(customer_three), "call_and_chat_customers": sum("hotline" in cs and bool(cs - {"hotline"}) for cs in channel_sets.values()), "channels": dict(channels), "personas": dict(personas), "catalog_categories": sorted(categories_used), "active_catalog_leaf_skus": sum(not r["discontinued"] for r in sku_rows)}
    counts["call_and_chat_customers_within_journey"] = len(customer_linked_channels)
    counts["customers_with_two_hotline_calls_in_journey"] = len(customer_two_hotline)
    for key, value in counts.items():
        check(coverage["counts"][key] == value, f"coverage count mismatch: {key}")
    targets = requirements["requirements"]
    minimums = {"transcripts": counts["transcripts"], "multi_session_customers": counts["multi_session_customers"], "customers_with_three_call_journey": counts["customers_with_three_call_journey"], "call_and_chat_customers": counts["call_and_chat_customers_within_journey"], "categories": len(categories_used), "catalog_skus": counts["active_catalog_leaf_skus"], "evaluation_scenarios": len(scenarios)}
    minimums["customers_with_two_hotline_calls_in_journey"] = counts["customers_with_two_hotline_calls_in_journey"]
    for key, value in minimums.items():
        check(value >= targets[key], f"M2 text minimum {key}: {value} < {targets[key]}")
    for persona in requirements["required_personas"]:
        check(personas[persona] > 0, f"missing required persona {persona}")
    planned_tids = [r["transcript_id"] for r in plan]
    check(len(set(planned_tids)) == len(plan), "duplicate recording target")
    check(set(planned_tids) == {t for t, x in by_transcript.items() if x["channel"] == "hotline"}, "recording plan differs from hotline transcripts")
    check(len(plan) >= targets["audio_conversations"], "insufficient planned recordings")
    check(len({r["customer_voice_region"] for r in plan}) >= targets["voice_regions"], "insufficient planned regional voices")
    check(sum(r["noise_required"] for r in plan) / len(plan) >= targets["noisy_audio_fraction"], "insufficient planned noise")
    for row in plan:
        check(row["audio_path"] is None and row["actual_duration_seconds"] is None and row["segments_path"] is None, f"fabricated recording {row['transcript_id']}")
        check(row["status"] == "pending_recording" and row["duration_is_estimate"], f"mislabelled recording plan {row['transcript_id']}")
    return {"status": "pass" if not errors else "fail", "scope": "authored text fixtures only; no agent performance or audio completion claimed", "numbering": numbering, "counts": counts, "checks": {"reference_tool_executions_replayed": tools_replayed, "positive_call_assertions": positive_checks, "negative_order_probes": negative_checks, "source_hashes": len(coverage["source_sha256"])}, "text_m2_minimums_met": not errors, "catalog_counting": "128 active distinct leaf SKUs, including size/color variants; 40 parent product models", "audio_m2_minimums_met": False, "pending": ["record at least 100 two-speaker conversations totaling at least 10800 measured seconds", "verify three actual regional voices and noise on at least 20% of actual recordings", "derive diarization timestamps from completed audio", "human semantic review; real-agent and three-seed simulator runs"], "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write the fixture validation report")
    args = parser.parse_args()
    result = validate()
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
