"""Checkpointable, provider-independent transcript transitions.

The active coding agent supplies responses. This module never calls a model.
"""
from __future__ import annotations

import copy
import hashlib
import json

from .checks import validate_schema, validate_transcript
from .common import HERE, fingerprint, read
from .duplicates import DuplicateIndex
from .review import review_record, validate_review
from .runner import JUDGE_SCHEMA, entity_values, journey_artifacts, parse_response, request


def json_file_hash(value) -> str:
    return hashlib.sha256((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()).hexdigest()


def initial_state() -> dict:
    return {"format_version": 1, "position": 0, "attempt": 1, "phase": "generate", "history": [],
            "decisions": [], "feedback": [], "candidate": None, "similarity": None,
            "duplicate_cursor": 0, "generation_request_sha256": None, "audit": [], "reviews": [],
            "accepted": [], "quarantine": [], "calls": 0, "last_event_sha256": None,
            "status": "awaiting_task", "sessions": [], "budget_observations": []}


def current_request(state: dict, plans: list[dict], config: dict) -> dict:
    plan = plans[state["position"]]
    if state["phase"] == "generate" and state.get("generation_unit") == "journey":
        schema = {"type": "object", "additionalProperties": False, "required": ["transcripts"],
                  "properties": {"transcripts": {"type": "array", "minItems": len(plan["sessions"]),
                                  "maxItems": len(plan["sessions"]), "items": read(HERE / "response.schema.json")}}}
        req = request("generate", {"journey_plan": plan, "validation_feedback": state["feedback"],
                                  "limits": config["validation"]}, schema)
        req.update(kind="generate_journey", schema_name="journey_transcripts")
        req["messages"][0]["content"] += "\nViết toàn bộ hành trình trong transcripts, đúng thứ tự phiên. Kế hoạch có cả phiên tương lai để tổ chức mạch truyện; từng lượt chỉ được dùng facts phiên hiện tại và thông tin đã được nói ở phiên trước. Không tiết lộ quyết định/ngân sách/mã đơn của phiên sau sớm hơn."
        return req
    if state["phase"] == "generate":
        return request("generate", {"session_plan": plan["sessions"][len(state["history"])],
                                   "previous_sessions": state["history"], "validation_feedback": state["feedback"],
                                   "limits": config["validation"]}, read(HERE / "response.schema.json"))
    if state["phase"] == "duplicate":
        match = state["similarity"]["matches"][state["duplicate_cursor"]]
        return request("duplicate", {"candidate": {"utterances": state["candidate"]["utterances"]},
                                     "reference": match["reference"]}, JUDGE_SCHEMA)
    return request("quality_review", {"journey_plan": plan, "transcripts": state["history"]},
                   read(HERE / "review.schema.json"))


def build_index(state: dict, plans: list[dict], catalog: list[dict], references: list[dict]) -> DuplicateIndex:
    index = DuplicateIndex(state.setdefault("duplicate_features", {}))
    entities = [p["name"] for p in catalog] + [p["sku"] for p in catalog]
    for i, reference in enumerate(references):
        index.add(reference, entities, f"reference:{i:06d}.json")
    for accepted in state["accepted"]:
        plan = plans[accepted["position"]]
        for transcript, session in zip(accepted["history"], plan["sessions"]):
            index.add(transcript, entity_values(session), f"run:{plan['journey_id']}")
    if state["position"] < len(plans):
        plan = plans[state["position"]]
        for transcript, session in zip(state["history"], plan["sessions"]):
            index.add(transcript, entity_values(session), f"run:{plan['journey_id']}")
    return index


def clear_attempt(state: dict) -> None:
    state.update(phase="generate", history=[], decisions=[], candidate=None, similarity=None,
                 duplicate_cursor=0, generation_request_sha256=None, pending_candidates=[])


def advance(state: dict, plans: list[dict]) -> None:
    state.update(position=state["position"] + 1, attempt=1, feedback=[])
    clear_attempt(state)
    if state["position"] == len(plans):
        state["status"] = "ready_to_finalize"


def fail_attempt(state: dict, plans: list[dict], config: dict, errors: list[str]) -> None:
    state["feedback"] = errors
    state["attempt"] += 1
    clear_attempt(state)
    if state["attempt"] > config["generation"]["max_attempts"]:
        state["quarantine"].append({"journey_id": plans[state["position"]]["journey_id"],
                                    "errors": errors, "status": "quarantined"})
        advance(state, plans)


def finish_session(state: dict, plans: list[dict], config: dict, errors: list[str]) -> None:
    plan = plans[state["position"]]
    session = plan["sessions"][len(state["history"])]
    decision = {"transcript_id": session["transcript_id"], "attempt": state["attempt"],
                "request_sha256": state["generation_request_sha256"], "errors": errors,
                "duplicate_result": copy.deepcopy(state["similarity"])}
    state["audit"].append(decision)
    if errors:
        fail_attempt(state, plans, config, [f"{session['transcript_id']}: {error}" for error in errors])
    else:
        state["decisions"].append(decision)
        state["history"].append(state["candidate"])
        state.update(candidate=None, similarity=None, duplicate_cursor=0,
                     phase="quality_review" if len(state["history"]) == len(plan["sessions"]) else "generate")


def consume_candidates(state: dict, plans: list[dict], catalog: list[dict], references: list[dict], config: dict) -> None:
    """Validate a batch in order; pause only when a duplicate judge is needed."""
    while state.get("pending_candidates"):
        candidate = state["pending_candidates"].pop(0)
        session = plans[state["position"]]["sessions"][len(state["history"])]
        errors = validate_transcript(candidate, session, state["history"], config["validation"])
        state.update(candidate=candidate, similarity=None)
        if not errors:
            result = build_index(state, plans, catalog, references).compare(candidate, entity_values(session), config["duplicates"])
            state["similarity"] = result
            if result["decision"] == "reject":
                errors = ["duplicate: wording/structure too close to " + result["matches"][0]["transcript_id"]]
            elif result["decision"] == "review":
                if config["duplicates"]["judge_ambiguous"]:
                    state.update(phase="duplicate", duplicate_cursor=0)
                    return
                errors = ["duplicate: ambiguous similarity requires a judge or rewrite"]
        finish_session(state, plans, config, errors)
        if errors:
            return


def consume(state: dict, plans: list[dict], catalog: list[dict], references: list[dict],
            config: dict, req: dict, response: dict) -> dict:
    """Apply exactly one response; caller owns atomic journaling/checkpointing."""
    state = copy.deepcopy(state)
    if req != current_request(state, plans, config):
        raise ValueError("submitted request differs from the expected task")
    state["calls"] += 1
    plan = plans[state["position"]]
    if state["phase"] == "generate" and state.get("generation_unit") == "journey":
        state["generation_request_sha256"] = fingerprint(req)
        try:
            body = parse_response(response)
            errors = validate_schema(body, req["schema"])
        except (ValueError, TypeError, KeyError):
            errors = ["format: incomplete or invalid journey JSON"]
        if errors:
            fail_attempt(state, plans, config, errors)
        else:
            state["pending_candidates"] = body["transcripts"]
            consume_candidates(state, plans, catalog, references, config)
    elif state["phase"] == "generate":
        state["generation_request_sha256"] = fingerprint(req)
        state["similarity"] = None
        session = plan["sessions"][len(state["history"])]
        try:
            candidate = parse_response(response)
            errors = validate_transcript(candidate, session, state["history"], config["validation"])
        except (ValueError, TypeError, KeyError):
            candidate, errors = None, ["format: response is incomplete or not valid transcript JSON"]
        state["candidate"] = candidate
        if not errors:
            result = build_index(state, plans, catalog, references).compare(candidate, entity_values(session), config["duplicates"])
            state["similarity"] = result
            if result["decision"] == "reject":
                errors = ["duplicate: wording/structure too close to " + result["matches"][0]["transcript_id"] + "; vary narrative and phrasing, preserve facts"]
            elif result["decision"] == "review":
                if config["duplicates"]["judge_ambiguous"]:
                    state.update(phase="duplicate", duplicate_cursor=0)
                    return state
                errors = ["duplicate: ambiguous similarity requires an automated judge or a more distinct rewrite"]
        finish_session(state, plans, config, errors)
    elif state["phase"] == "duplicate":
        errors = []
        try:
            decision = parse_response(response)
            if not isinstance(decision, dict) or set(decision) != {"duplicate", "reason"} or type(decision["duplicate"]) is not bool or not isinstance(decision["reason"], str) or not decision["reason"].strip():
                raise ValueError("invalid duplicate judge schema")
            state["similarity"]["matches"][state["duplicate_cursor"]]["judge"] = decision
            if decision["duplicate"]:
                errors = ["duplicate: " + decision["reason"]]
        except (ValueError, TypeError, KeyError):
            errors = ["duplicate: judge response invalid; no automatic acceptance"]
        state["duplicate_cursor"] += 1
        if errors or state["duplicate_cursor"] == len(state["similarity"]["matches"]):
            finish_session(state, plans, config, errors)
            if not errors and state.get("generation_unit") == "journey":
                consume_candidates(state, plans, catalog, references, config)
    else:
        decision = None
        try:
            decision = parse_response(response)
            errors = validate_review(decision, plan["journey_id"], state["history"])
        except (ValueError, TypeError, KeyError):
            errors = ["review: incomplete or invalid rubric response; cannot automatically approve"]
        review = review_record(plan, state["history"], req, response, decision, errors)
        path = f"reviews/{plan['journey_id']}/attempt_{state['attempt']:02d}.json"
        state["reviews"].append({"path": path, "record": review, "attempt": state["attempt"]})
        if not errors:
            _, errors = journey_artifacts(plan, state["history"], state["decisions"], json_file_hash(review),
                                         read(HERE / "transcript.schema.json"))
        if errors:
            fail_attempt(state, plans, config, errors)
        else:
            state["accepted"].append({"position": state["position"], "history": state["history"],
                                      "decisions": state["decisions"], "review_path": path,
                                      "review_sha256": json_file_hash(review)})
            advance(state, plans)
    return state
