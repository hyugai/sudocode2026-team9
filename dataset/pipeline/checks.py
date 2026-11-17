from __future__ import annotations

import re
import unicodedata
from datetime import date

from .common import HERE, read

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
FIELDS = {"transcript_id", "customer_id", "session_index", "channel", "outcome", "utterances"}


def validate_schema(value, schema: dict, path: str = "$output") -> list[str]:
    """Validate the JSON Schema subset used by this pipeline's versioned schemas."""
    types = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
             "string": lambda x: isinstance(x, str), "integer": lambda x: type(x) is int,
             "boolean": lambda x: type(x) is bool, "null": lambda x: x is None}
    expected = schema.get("type")
    expected = expected if isinstance(expected, list) else [expected]
    if expected != [None] and not any(types[t](value) for t in expected):
        return [f"schema: {path} has wrong type"]
    errors = []
    if "enum" in schema and not any(type(value) is type(v) and value == v for v in schema["enum"]):
        errors.append(f"schema: {path} has invalid enum value")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - value.keys():
            errors.append(f"schema: {path} is missing required fields")
        if schema.get("additionalProperties") is False and value.keys() - properties.keys():
            errors.append(f"schema: {path} contains unexpected fields")
        for key in value.keys() & properties.keys():
            errors.extend(validate_schema(value[key], properties[key], f"{path}.{key}"))
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            errors.append(f"schema: {path} has wrong item count")
        for i, item in enumerate(value):
            if "items" in schema:
                errors.extend(validate_schema(item, schema["items"], f"{path}[{i}]"))
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"schema: {path} is too short")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"schema: {path} does not match the required pattern")
        if schema.get("format") == "date":
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError("noncanonical date")
            except ValueError:
                errors.append(f"schema: {path} must be an ISO date")
    return errors


def text_key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def numbers(value) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(numbers(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(numbers(v) for v in value)) if value else set()
    return {re.sub(r"[.,]", "", m) for m in NUMBER.findall(str(value))}


def validate_transcript(candidate, session: dict, previous: list[dict], limits: dict) -> list[str]:
    errors = validate_schema(candidate, read(HERE / "response.schema.json"))
    if errors:
        return errors
    if not isinstance(candidate, dict) or set(candidate) != FIELDS:
        return ["schema: transcript fields must match the supplied schema exactly"]
    for key in ("transcript_id", "customer_id", "session_index", "channel"):
        if type(candidate[key]) is not type(session[key]) or candidate[key] != session[key]:
            errors.append(f"identity: {key} changed")
    if candidate["outcome"] != session["expected_outcome"]:
        errors.append("business: outcome differs from verified reference event")
    turns = candidate["utterances"]
    if not isinstance(turns, list) or not limits["min_turns"] <= len(turns) <= limits["max_turns"]:
        return errors + ["schema: turn count outside configured limits"]
    if len(turns) % 2:
        errors.append("schema: conversation must end with agent after alternating turns")
    for i, turn in enumerate(turns):
        if not isinstance(turn, dict) or set(turn) != {"speaker", "text"}:
            errors.append(f"schema: invalid turn {i}")
            continue
        if turn["speaker"] != ("customer" if i % 2 == 0 else "agent"):
            errors.append(f"schema: wrong speaker at turn {i}")
        if not isinstance(turn["text"], str) or not turn["text"].strip() or len(turn["text"]) > 4000:
            errors.append(f"schema: invalid text at turn {i}")
    if any(e.startswith("schema:") for e in errors):
        return errors
    combined = " ".join(t["text"] for t in turns)
    agent = " ".join(t["text"] for t in turns if t["speaker"] == "agent")
    if len(combined.split()) < limits["min_words"]:
        errors.append("quality: dialogue too short to establish the planned facts")
    if re.search(r"\b0\d{9,11}\b", combined):
        errors.append("quality: unexpected phone/identity-number pattern in synthetic dialogue")
    allowed = numbers([session, previous])
    unknown = numbers(combined) - allowed
    if unknown:
        errors.append("facts: unsupported numeric values; retain only supplied facts")
    p = session["facts"]["product"]
    if text_key(p["name"]) not in text_key(combined) and text_key(p["sku"]) not in text_key(combined):
        errors.append("facts: planned product is absent")
    required = session["required_any"]
    if required and not any(text_key(a) in text_key(agent) for a in required):
        errors.append("business: missing required acknowledgment: " + " / ".join(required))
    event = session["reference_event"]
    if event["action"] in {"order.create", "order.update"}:
        order = event["result"].get("order_id")
        if order and order not in agent:
            errors.append("business: reference order ID must appear in agent response")
    elif not any(p["outcome"] == "order.create" for p in previous) and re.search(r"đã\s+(?:tạo|lên|chốt)\s+đơn", agent, re.I):
        errors.append("business: claims a completed order without a reference event")
    if session["hard_case"] == "unknown_information" and re.search(r"serial\s*(?:là|:)\s*\w+", agent, re.I):
        errors.append("business: unverified serial claim")
    # Literal quoted monetary claims are checked separately from general numbers.
    allowed_prices = {session["facts"]["price_vnd"], session["facts"]["customer_budget_vnd"]}
    for old in previous:
        allowed_prices.update(int(n) for n in numbers(old) if n.isdigit())
    for match in re.finditer(r"(\d{1,3}(?:[.,]\d{3})+|\d{5,})\s*(?:đồng|vnd|đ\b)", combined, re.I):
        amount = int(re.sub(r"[.,]", "", match[1]))
        if amount not in allowed_prices and str(amount) not in numbers(session["reference_event"]):
            # Policy amounts are legitimate when explicitly present in selected sources.
            if str(amount) not in numbers(session["facts"]["policies"]):
                errors.append("facts: unsupported monetary amount")
    return errors
