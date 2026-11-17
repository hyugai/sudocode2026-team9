#!/usr/bin/env python3
"""Create review-only LLM language variants of the verified M2 fixtures.

Default mode prepares original-text requests without calling a model. --generate uses
the project's model factory; --responses replays saved JSON responses offline.
Neither mode overwrites or promotes the original corpus.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
NUMBER = re.compile(r"\d+(?:[.,:/–-]\d+)*")
ENTITY_KEYS = {
    "name", "customer_name", "phone", "customer_phone", "address",
    "delivery_address", "shipping_address", "channel_identity", "customer_id",
    "fb_id", "zalo_id", "sku", "variant_sku", "parent_sku", "promo_code", "order_id",
}
PHRASE_KEYS = {"must_say_any", "agent_must_say", "brief_must_contain"}


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def literals(value: Any, key: str = "") -> set[str]:
    """Find immutable entities and grading phrases for response checks only."""
    if isinstance(value, dict):
        return set().union(*(literals(v, k) for k, v in value.items())) if value else set()
    if isinstance(value, list):
        return set().union(*(literals(v, key) for v in value)) if value else set()
    if isinstance(value, str) and key in ENTITY_KEYS | PHRASE_KEYS and value.strip():
        return {value}
    return set()


def prepare(sid: str) -> tuple[dict, set[str], dict, list[dict]]:
    scenario = read(HERE / "scenarios_complete" / f"{sid}.json")
    metadata = read(HERE / "scenario_metadata.json")[sid]
    transcripts = [read(HERE / "conversations" / f"{sid}-{call}.json") for call in scenario["calls"]]
    protected = literals(scenario) | literals(metadata) | literals(transcripts)
    sessions = []
    for t in transcripts:
        noisy = "customer_turns_asr" in scenario["calls"][t["call"]]
        sessions.append({
            "transcript_id": t["transcript_id"], "channel": t["channel"],
            "utterances": [{"speaker": u["speaker"], "text": u["text"],
                            "locked": noisy and u["speaker"] == "customer"}
                           for u in t["utterances"]],
        })
    request = {"scenario_id": sid, "persona": scenario["persona"], "sessions": sessions}
    return request, protected, scenario, transcripts


def validate_response(request: dict, response: Any, protected: set[str]) -> list[str]:
    errors = []
    ordered = sorted(protected, key=lambda s: (-len(s), s))
    entities = re.compile("|".join(r"(?<!\w)" + re.escape(s) + r"(?!\w)" for s in ordered)) if ordered else None
    if not isinstance(response, dict) or set(response) != {"scenario_id", "sessions"}:
        return ["response must contain only scenario_id and sessions"]
    if response["scenario_id"] != request["scenario_id"]:
        errors.append("scenario_id changed")
    sessions = response["sessions"]
    if not isinstance(sessions, list) or len(sessions) != len(request["sessions"]):
        return errors + ["session count changed"]
    for original, rewritten in zip(request["sessions"], sessions):
        tid = original["transcript_id"]
        if not isinstance(rewritten, dict) or set(rewritten) != {"transcript_id", "utterances"}:
            errors.append(f"{tid}: invalid session fields")
            continue
        if rewritten["transcript_id"] != tid:
            errors.append(f"{tid}: transcript order or identity changed")
        turns = rewritten["utterances"]
        if not isinstance(turns, list) or len(turns) != len(original["utterances"]):
            errors.append(f"{tid}: turn count changed")
            continue
        for index, (old, new) in enumerate(zip(original["utterances"], turns)):
            label = f"{tid}/{index}"
            if not isinstance(new, dict) or set(new) != {"speaker", "text"}:
                errors.append(f"{label}: only speaker and text are allowed")
                continue
            if new["speaker"] != old["speaker"]:
                errors.append(f"{label}: speaker changed")
            text = new["text"]
            if not isinstance(text, str) or not text.strip() or len(text) > 2 * len(old["text"]) + 300:
                errors.append(f"{label}: empty, invalid or excessively long text")
                continue
            if old["locked"] and text != old["text"]:
                errors.append(f"{label}: noisy customer input must remain unchanged")
            if NUMBER.findall(text) != NUMBER.findall(old["text"]):
                errors.append(f"{label}: numeric values or their order changed")
            if entities and entities.findall(text) != entities.findall(old["text"]):
                errors.append(f"{label}: protected entities or phrases changed")
    return errors


def materialize(request: dict, response: dict, protected: set[str], scenario: dict,
                transcripts: list[dict]) -> tuple[dict, list[dict]]:
    errors = validate_response(request, response, protected)
    if errors:
        raise ValueError("; ".join(errors))
    scenario = copy.deepcopy(scenario)
    candidates = copy.deepcopy(transcripts)
    for candidate, session in zip(candidates, response["sessions"]):
        for u, new in zip(candidate["utterances"], session["utterances"]):
            u["text"] = new["text"]
        scenario["calls"][candidate["call"]]["customer_turns"] = [
            u["text"] for u in candidate["utterances"] if u["speaker"] == "customer"]
        candidate["origin"] = "language_variant_reference_dialogue"
        candidate["private_annotations"]["review_status"] = "automated_checks_pending; human_semantic_review_pending"
    return scenario, candidates


def check_business(scenario: dict, transcripts: list[dict]) -> list[str]:
    from build_corpus import reference_module
    from validate_corpus import replay, rows_for

    mock = reference_module("naturalize_mock", "mock_tools.py")
    evaluator = reference_module("naturalize_evaluator", "reference_eval.py")
    aliases: set[str] = set()
    errors = []
    for t in transcripts:
        tools = t["private_annotations"]["reference_tool_executions"]
        errors.extend(f"{t['transcript_id']}: {error}" for error in replay(mock, tools))
        rows = rows_for(t)
        passed, reasons = evaluator.check_call(scenario["calls"][t["call"]], rows, aliases)
        if not passed:
            errors.append(f"{t['transcript_id']}: BTC assertions failed: {reasons}")
        aliases.update(evaluator.created_order_ids(rows))
        agent_text = " ".join(u["text"] for u in t["utterances"] if u["speaker"] == "agent")
        if re.search(r"\b0\d{9}\b|\b\d+ đường Kiểm Thử", agent_text):
            errors.append(f"{t['transcript_id']}: agent exposes phone/street number")
    return errors


def model_client(args) -> tuple[Any, dict]:
    """Only live mode imports optional project dependencies or loads credentials."""
    sys.path.insert(0, str(REPO / "src"))
    from dotenv import load_dotenv
    from telesale_agent.adapters.llm.model_factory import create_chat_model, resolve_model_config

    load_dotenv(REPO / ".env")
    config = resolve_model_config(provider=args.provider, model_name=args.model,
                                  max_output_tokens=args.max_output_tokens)
    thinking = args.thinking_level or os.environ.get("LLM_THINKING_LEVEL") or None
    client = create_chat_model(temperature=args.temperature, provider=args.provider,
                               model_name=args.model, max_output_tokens=args.max_output_tokens,
                               thinking_level=thinking)
    versions = {}
    for package in ("langchain-core", "langchain-google-genai", "langchain-groq"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    # Never serialize ModelConfig: it includes the API key.
    return client, {"provider": config.provider, "requested_model": config.model,
                    "temperature_requested": args.temperature,
                    "sampling_note": "model factory may omit temperature for fixed-sampling models",
                    "max_output_tokens": config.max_output_tokens, "timeout": config.timeout,
                    "max_retries": config.max_retries, "thinking_level_requested": thinking,
                    "groq_reasoning_effort": os.environ.get("GROQ_REASONING_EFFORT"),
                    "packages": versions, "seed": None}


def response_text(message: Any) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(block["text"] for block in message.content
                   if isinstance(block, dict) and isinstance(block.get("text"), str)
                   and block.get("type") == "text")


def run(args) -> int:
    from validate_corpus import validate

    baseline = validate()
    if baseline["status"] != "pass":
        raise ValueError("baseline validation failed; resolve it before language generation")
    ids = args.scenario or ["SC-121"]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"SC-\d{3}", sid) for sid in ids):
        raise ValueError("scenario IDs must be distinct SC-xxx identifiers")
    prepared = {sid: prepare(sid) for sid in ids}
    output = args.output.resolve()
    if output.is_relative_to((REPO / "dataset").resolve()) or HERE.is_relative_to(output):
        raise ValueError("output must be outside dataset/ and must not contain the source tree")
    # Each run is immutable; retry/import into a new directory instead of overwriting evidence.
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / ".gitignore").write_text("*\n", encoding="utf-8")
    prompt_path = HERE / "naturalize_prompt.md"
    system = prompt_path.read_text(encoding="utf-8")
    (output / "system_prompt.md").write_text(system, encoding="utf-8")
    inputs = [Path(__file__), prompt_path, HERE / "scenario_metadata.json", HERE / "coverage.json",
              HERE / "validate_corpus.py", HERE / "build_corpus.py",
              HERE.parent / "bug-format.md", HERE.parent / "bug-quality.md"]
    inputs += [HERE / "scenarios_complete" / f"{sid}.json" for sid in ids]
    inputs += [HERE / "conversations" / f"{t['transcript_id']}.json"
               for _, _, _, transcripts in prepared.values() for t in transcripts]
    source_hashes = read(HERE / "coverage.json")["source_sha256"]
    inputs += [REPO / "dataset/organizer" / name for name in source_hashes]
    metadata = {"format_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "mode": "live" if args.generate else "replay" if args.responses else "prepare",
                "scenario_ids": ids, "source_sha256": {str(p.relative_to(REPO)): digest(p) for p in inputs},
                "status": "prepared", "is_actual_agent_trace": False, "model": None,
                "input_text_handling": "original_dialogue_without_masking",
                "limitations": ["Entity, numeric and BTC checks cannot prove semantic equivalence or naturalness.",
                                "Human review is mandatory; candidates are never promoted automatically.",
                                "Replayed raw responses provide repeatability; model regeneration is not bit-exact.",
                                "Live model messages contain original dialogue, including any personal identifiers."]}
    for sid, (request, _, _, _) in prepared.items():
        write(output / "requests" / f"{sid}.json", request)
        write(output / "messages" / f"{sid}.json", [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False, indent=2)},
        ])
    if args.responses:
        archived = args.responses.parent / "run.json"
        if archived.is_file():
            prior = read(archived)
            if any(prior.get("source_sha256", {}).get(k) != v for k, v in metadata["source_sha256"].items()):
                raise ValueError("archived response source hashes differ; prepare a new generation run")
            for sid in ids:
                if read(args.responses.parent / "messages" / f"{sid}.json") != read(output / "messages" / f"{sid}.json"):
                    raise ValueError("archived prompt differs; cannot claim an identical replay")
            metadata["response_source"] = {"status": "archived_inputs_verified", "run_sha256": digest(archived)}
        else:
            metadata["response_source"] = {"status": "imported_response_without_verified_run_history"}
    write(output / "run.json", metadata)
    client = None
    if args.generate:
        try:
            client, metadata["model"] = model_client(args)
            metadata["status"] = "generating"
            write(output / "run.json", metadata)
        except Exception as exc:
            metadata.update(status="provider_setup_failed", error_type=type(exc).__name__)
            write(output / "run.json", metadata)
            raise RuntimeError("model setup failed; check project dependencies and provider configuration") from None
    report = {"status": "prepared", "scope": "selected transcript candidates only", "scenarios": {}}
    manifest = []
    for sid, (request, protected, scenario, transcripts) in prepared.items():
        if not args.generate and not args.responses:
            continue
        errors = []
        raw = None
        try:
            if client is not None:
                messages = read(output / "messages" / f"{sid}.json")
                message = client.invoke([("system", messages[0]["content"]), ("human", messages[1]["content"])])
                raw = response_text(message)
                provider_meta = getattr(message, "response_metadata", {}) or {}
                write(output / "provider_metadata" / f"{sid}.json", {
                    "usage": getattr(message, "usage_metadata", None),
                    "response": {k: provider_meta[k] for k in ("model_name", "model", "finish_reason", "system_fingerprint") if k in provider_meta}})
            else:
                raw = (args.responses / f"{sid}.json").read_text(encoding="utf-8")
            raw_path = output / "raw_responses" / f"{sid}.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(raw, encoding="utf-8")
            response = json.loads(raw)
            errors = validate_response(request, response, protected)
            if not errors:
                candidate_scenario, candidates = materialize(request, response, protected, scenario, transcripts)
                errors = check_business(candidate_scenario, candidates)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            # Error strings can include raw identifiers or provider secrets; log types only.
            errors = [f"processing failed: {type(exc).__name__}"]
        except Exception as exc:
            errors = [f"provider failed: {type(exc).__name__}; no automatic whole-scenario retry"]
        report["scenarios"][sid] = {"status": "rejected" if errors else "candidate_pending_human_review", "errors": errors}
        if errors:
            continue
        for candidate, original in zip(candidates, transcripts):
            candidate["private_annotations"]["review_status"] = "automated_checks_passed; human_semantic_review_pending"
            candidate["private_annotations"]["language_generation"] = {
                "run_metadata": "../../run.json", "source_transcript_sha256": digest(HERE / "conversations" / f"{original['transcript_id']}.json"),
                "request_sha256": digest(output / "requests" / f"{sid}.json"),
                "response_sha256": digest(output / "raw_responses" / f"{sid}.json")}
            path = output / "candidates/conversations" / f"{candidate['transcript_id']}.json"
            write(path, candidate)
            manifest.append({"transcript_id": candidate["transcript_id"], "scenario_id": sid,
                             "conversation_path": str(path.relative_to(output)), "conversation_sha256": digest(path),
                             "status": "candidate_pending_human_review", "audio_path": None,
                             "changed_turns": sum(a["text"] != b["text"] for a, b in zip(candidate["utterances"], original["utterances"]))})
        write(output / "candidates/scenarios_complete" / f"{sid}.json", candidate_scenario)
    if args.generate or args.responses:
        report["status"] = "rejected" if any(v["errors"] for v in report["scenarios"].values()) else "candidate_pending_human_review"
    metadata["status"] = report["status"]
    write(output / "run.json", metadata)
    write(output / "validation_report.json", report)
    (output / "manifest.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in manifest), encoding="utf-8")
    print(json.dumps({"status": report["status"], "scenarios": len(ids), "candidate_transcripts": len(manifest), "output": str(output)}, ensure_ascii=False))
    return 2 if report["status"] == "rejected" else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new directory outside dataset/")
    parser.add_argument("--scenario", action="append", help="whole journey; repeat for more (default SC-121)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--generate", action="store_true", help="call the configured external model")
    mode.add_argument("--responses", type=Path, help="offline directory with SC-xxx.json original-text responses")
    parser.add_argument("--provider", choices=("gemini", "groq"))
    parser.add_argument("--model", help="explicit provider model ID; no implicit default")
    parser.add_argument("--temperature", type=float, default=0.5)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--thinking-level", choices=("minimal", "low", "medium", "high"))
    args = parser.parse_args()
    if args.generate and (not args.provider or not args.model):
        parser.error("--generate requires explicit --provider and --model")
    if not math.isfinite(args.temperature) or not 0 <= args.temperature <= 2 or args.max_output_tokens <= 0:
        parser.error("temperature must be between 0 and 2; max-output-tokens must be positive")
    try:
        return run(args)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
