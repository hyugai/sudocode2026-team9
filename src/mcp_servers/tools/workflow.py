"""Workflow domain tools — schedule.callback, handoff.transfer"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from mcp_servers.tools.business_calendar import callback_datetime
from telesale_agent.core.briefs import HandoffBrief


def _next_working_datetime(dt: datetime) -> tuple[datetime, bool]:
    adjusted = callback_datetime(dt)
    return adjusted, adjusted != dt


def schedule_callback(
    customer_phone: str,
    callback_at: str,
    note: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Schedule a callback using the BTC holiday and opening-hour rules.

    BTC tool name: schedule.callback
    The agent MUST inform the customer whenever moved_from is not null.
    """
    callback_dt = datetime.fromisoformat(callback_at)
    adjusted_dt, was_moved = _next_working_datetime(callback_dt)

    callback_id = f"CB-{uuid.uuid4().hex[:6].upper()}"
    return {
        "callback_id": callback_id,
        "customer_phone": customer_phone,
        "callback_at": adjusted_dt.isoformat(timespec="minutes"),
        "moved_from": callback_at if was_moved else None,
        "note": note,
    }


def handoff_transfer(
    brief: dict[str, Any],
    on: str | None = None,
) -> dict[str, Any]:
    """Transfer to a human agent with a HandoffBrief.

    BTC tool name: handoff.transfer
    brief must conform to schemas/handoff_brief.schema.json (required fields).
    """
    required_fields = set(HandoffBrief.model_json_schema()["required"])
    missing = sorted(required_fields - brief.keys())
    if missing:
        return {"error": "brief_invalid", "missing": missing}
    try:
        HandoffBrief.model_validate(brief)
    except ValidationError:
        return {"error": "brief_invalid"}

    ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    return {"ticket_id": ticket_id, "status": "queued", "brief_ok": True}


TOOLS = {
    "schedule.callback": schedule_callback,
    "handoff.transfer": handoff_transfer,
}
