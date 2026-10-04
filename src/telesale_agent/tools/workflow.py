"""Workflow domain tools — schedule.callback, handoff.transfer"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

REFERENCE_DATE = date(2026, 10, 15)

# Official holidays for the competition period (extend as needed)
_HOLIDAYS: set[date] = {
    date(2026, 10, 20),
    date(2026, 11, 20),
}


def _next_working_datetime(dt: datetime) -> tuple[datetime, bool]:
    """Shift dt to next working day if it falls on a weekend or holiday.
    Returns (adjusted_dt, was_moved).
    """
    original = dt
    while dt.weekday() >= 5 or dt.date() in _HOLIDAYS:  # 5=Sat, 6=Sun
        dt += timedelta(days=1)
        # Keep the same time of day on the new date
        dt = dt.replace(hour=original.hour, minute=original.minute, second=0)
    return dt, dt != original


def schedule_callback(
    customer_phone: str,
    callback_at: str,
    note: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Schedule a callback. Auto-reschedules if it falls on a holiday or weekend.

    BTC tool name: schedule.callback
    The agent MUST inform the customer whenever moved_from is not null.
    """
    callback_dt = datetime.fromisoformat(callback_at)
    adjusted_dt, was_moved = _next_working_datetime(callback_dt)

    callback_id = f"CB-{uuid.uuid4().hex[:6].upper()}"
    return {
        "callback_id": callback_id,
        "callback_at": adjusted_dt.isoformat(),
        "moved_from": callback_dt.isoformat() if was_moved else None,
    }


def handoff_transfer(
    brief: dict[str, Any],
    on: str | None = None,
) -> dict[str, Any]:
    """Transfer to a human agent with a HandoffBrief.

    BTC tool name: handoff.transfer
    brief must conform to schemas/handoff_brief.schema.json (required fields).
    """
    required_fields = {"reason", "customer_id", "summary"}
    missing = required_fields - set(brief.keys())
    if missing:
        return {"error": f"handoff_brief_missing_fields: {missing}"}

    ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    return {"ticket_id": ticket_id, "status": "queued"}


TOOLS = {
    "schedule.callback": schedule_callback,
    "handoff.transfer": handoff_transfer,
}
