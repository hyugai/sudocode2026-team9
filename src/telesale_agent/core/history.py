"""Small, read-only projections shared by chat history and voice journal writes."""
from dataclasses import asdict, is_dataclass
import json
import math
import re


MEMORY_FIELDS = (
    "customer_memory", "working_memory", "memory_deltas", "customer_profile",
    "past_history", "retrieved_data",
)
_PRIVATE = re.compile(r"password|passwd|secret|token|credential|api.?key|authorization|cookie|debug|checkpoint|tool_calls|tool_config", re.I)


def _display(value, depth=0):
    if depth > 12:
        raise ValueError("Snapshot lồng quá sâu.")
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: _display(item, depth + 1) for key, item in value.items()
                if isinstance(key, str) and not _PRIVATE.search(key)}
    if isinstance(value, list):
        return [_display(item, depth + 1) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("Snapshot không phải JSON hiển thị.")


def memory_preview(state) -> dict | None:
    """Never expose the complete checkpoint, identity, tools or runtime config."""
    if is_dataclass(state):
        state = {key: getattr(state, key, None) for key in MEMORY_FIELDS}
    if not isinstance(state, dict):
        return None
    try:
        result = {key: _display(state.get(key)) for key in MEMORY_FIELDS}
        memory = result.get("customer_memory")
        if isinstance(memory, dict):
            result["customer_memory"] = {key: memory[key] for key in (
                "customer_id", "profile", "behaviors", "facts", "atomic_facts", "episodes", "foresights"
            ) if key in memory}
        profile = result.get("customer_profile")
        if isinstance(profile, dict):
            result["customer_profile"] = {key: profile[key] for key in (
                "customer_id", "name", "phone", "email", "address", "tier", "attributes",
                "preferences", "history", "past_orders", "found",
            ) if key in profile}
        retrieved = result.get("retrieved_data")
        if isinstance(retrieved, dict):
            result["retrieved_data"] = {key: retrieved[key] for key in (
                "customer_history", "knowledge", "active_promotions"
            ) if key in retrieved}
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 256 * 1024:
            return None
        return result if any(value is not None for value in result.values()) else None
    except (TypeError, ValueError, RecursionError):
        return None


def brief_preview(value) -> dict | None:
    if is_dataclass(value):
        value = asdict(value)
    if not isinstance(value, dict):
        return None
    result = {"summary": value.get("summary", "")}
    if not isinstance(result["summary"], str):
        return None
    result["summary"] = result["summary"][:4000]
    for key in ("needs", "objections", "unresolved_issues"):
        items = value.get(key, [])
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            return None
        result[key] = [item[:1000] for item in items[:12]]
    return result
