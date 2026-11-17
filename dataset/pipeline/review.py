from __future__ import annotations

from .checks import validate_schema
from .common import HERE, fingerprint, read

CRITERIA = {"factuality", "continuity", "persona", "naturalness", "diversity", "outcome_alignment", "privacy"}


def validate_review(decision, journey_id: str, transcripts: list[dict], schema: dict | None = None) -> list[str]:
    errors = validate_schema(decision, schema or read(HERE / "review.schema.json"), "$review")
    if errors:
        return errors
    if decision["journey_id"] != journey_id:
        errors.append("review: wrong journey_id")
    checks = decision["checks"]
    names = [c["criterion"] for c in checks]
    if len(names) != len(CRITERIA) or set(names) != CRITERIA:
        errors.append("review: every rubric criterion must appear exactly once")
    by_id = {t["transcript_id"]: t for t in transcripts}
    for check in checks:
        label = check["criterion"]
        if not check["reason"].strip() or not check["evidence"]:
            errors.append(f"review: {label} needs a reason and cited evidence")
        if check["verdict"] != "pass":
            errors.append(f"review: {label}={check['verdict']}: {check['reason']}")
        cited = set()
        for e in check["evidence"]:
            t = by_id.get(e["transcript_id"])
            i = e["turn_index"]
            if t is None or i < 0 or i >= len(t["utterances"]) or not e["quote"].strip():
                errors.append(f"review: {label} has an invalid evidence reference")
            elif e["quote"] not in t["utterances"][i]["text"]:
                errors.append(f"review: {label} evidence is not an exact dialogue excerpt")
            else:
                cited.add(t["transcript_id"])
        if label == "continuity" and len(transcripts) > 1 and len(cited) < 2:
            errors.append("review: continuity must cite at least two sessions")
    return errors


def review_record(plan: dict, transcripts: list[dict], request: dict, response: dict, decision, errors: list[str]) -> dict:
    return {"journey_id": plan["journey_id"], "mode": "automated_llm_rubric",
            "status": "rejected" if errors else "automated_approved",
            "request_sha256": fingerprint(request), "response_sha256": fingerprint(response),
            "decision": decision, "errors": errors}
