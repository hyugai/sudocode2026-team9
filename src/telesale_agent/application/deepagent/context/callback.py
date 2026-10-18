"""Normalize callback requests and verified schedule adjustments."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from telesale_agent.core.models import TurnContext


def _normalize_callback_at(value: Any) -> str | None:
    """Normalize common callback timestamp shapes to an ISO minute string."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    candidates = [raw]
    # Gemini occasionally emits ``HH:MM YYYY-MM-DD`` for a Vietnamese phrase.
    reversed_match = re.fullmatch(
        r"(?P<time>\d{1,2}:\d{2})\s+(?P<date>\d{4}-\d{2}-\d{2})",
        raw,
    )
    if reversed_match:
        candidates.insert(
            0,
            f"{reversed_match.group('date')}T{reversed_match.group('time')}",
        )
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace(" ", "T", 1))
        except ValueError:
            continue
        return parsed.isoformat(timespec="minutes")
    return None

def _requested_callback_at(context: TurnContext) -> str | None:
    """Resolve the requested callback time from explicit current-turn evidence."""
    text = context.input.text or ""
    date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    time_match = re.search(
        r"\b([01]?\d|2[0-3])(?:\s*:\s*([0-5]\d)|\s*giờ(?:\s*([0-5]?\d)\s*phút)?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if date_match and time_match:
        minute = time_match.group(2) or time_match.group(3) or "00"
        return f"{date_match.group(1)}T{int(time_match.group(1)):02d}:{int(minute):02d}"

    sources: list[Any] = []
    if context.perception:
        if isinstance(context.perception.memory_deltas, dict):
            sources.append(context.perception.memory_deltas.get("callback_at"))
        if isinstance(context.perception.entities, dict):
            sources.append(context.perception.entities.get("callback_at"))
    return next(
        (
            normalized
            for value in sources
            if (normalized := _normalize_callback_at(value)) is not None
        ),
        None,
    )

def _callback_adjustment_note(tool_calls: list[dict[str, Any]]) -> str | None:
    """Return an authoritative customer-facing note for a moved callback."""
    for call in reversed(tool_calls):
        if call.get("name") != "schedule.callback":
            continue
        result = call.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        moved_from = _normalize_callback_at(result.get("moved_from"))
        actual = _normalize_callback_at(result.get("callback_at"))
        if not moved_from or not actual or moved_from == actual:
            return None
        requested_dt = datetime.fromisoformat(moved_from)
        actual_dt = datetime.fromisoformat(actual)
        return (
            "Lưu ý: lịch gọi lại ban đầu vào "
            f"{requested_dt:%H:%M ngày %d/%m/%Y} rơi vào ngày nghỉ, "
            "nên hệ thống đã chuyển lịch sang "
            f"{actual_dt:%H:%M ngày %d/%m/%Y}."
        )
    return None

